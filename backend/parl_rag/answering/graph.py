from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from typing_extensions import TypedDict

from ..retrieval.store import LanceDBStore, SearchHit
from ..settings import settings
from . import gate, llm, prompts
from .gate import QueryAssessment


@dataclass
class AskContext:
    """Per-run inputs that no node changes: the shared store plus the request's
    filters and retrieval knobs. Passed as ``context=`` when the graph is run."""

    store: LanceDBStore
    k: int = 5
    party: str | None = None
    speaker: str | None = None
    since: str | None = None
    until: str | None = None
    date: str | None = None
    rerank: bool = True
    route: bool = True


class AskState(TypedDict, total=False):
    """What the nodes produce. Every field is written once, so none needs a
    reducer. ``hits`` is the final grounded list (its order is the ``[S#]``
    numbering); ``candidates`` is the over-fetched pool when reranking."""

    question: str
    assessment: QueryAssessment      # gate
    candidates: list[SearchHit]      # retrieve
    hits: list[SearchHit]            # retrieve (no rerank / no rows) or rerank
    answer: str                      # generate
    model: str
    input_tokens: int
    output_tokens: int


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def check_answerable(state: AskState) -> dict:
    """Answerability gate: a too-broad question ("За какво говориха днес?") has
    no semantic anchor for the chunks, so grounding it would just confabulate.
    Fails open (gate.assess never raises), so a gate outage simply falls
    through to normal retrieval."""
    return {"assessment": gate.assess(state["question"])}


def retrieve(state: AskState, runtime: Runtime[AskContext]) -> dict:
    """Hybrid search with the metadata pre-filter. Writes ``hits`` itself when
    its result is already final: nothing matched, or reranking is off."""
    ctx = runtime.context
    candidates = ctx.store.hybrid_search(
        state["question"], k=ctx.k, party=ctx.party, speaker=ctx.speaker,
        since=ctx.since, until=ctx.until, date=ctx.date, rerank=ctx.rerank,
    )
    if ctx.rerank and candidates:
        return {"candidates": candidates}
    return {"candidates": candidates, "hits": candidates}


def rerank(state: AskState, runtime: Runtime[AskContext]) -> dict:
    """Cross-encode the candidate pool down to the top ``k``."""
    ctx = runtime.context
    return {"hits": ctx.store.rerank_hits(state["question"], state["candidates"], k=ctx.k)}


def generate_answer(state: AskState) -> dict:
    """Write the grounded, cited answer from ``hits``.

    A plain ``invoke``: when the graph is streamed with ``stream_mode="messages"``
    LangGraph still surfaces the tokens as the model produces them.
    """
    chunks = [h.chunk for h in state["hits"]]
    msg = llm.answer_model().invoke(prompts.build_messages(state["question"], chunks))
    usage = msg.usage_metadata or {}
    return {
        "answer": msg.text,
        "model": msg.response_metadata.get("model_name") or settings.llm_model,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def _enter(state: AskState, runtime: Runtime[AskContext]) -> Literal["gate", "retrieve"]:
    return "gate" if runtime.context.route else "retrieve"


def _after_gate(state: AskState) -> Literal["retrieve", "__end__"]:
    return "retrieve" if state["assessment"].answerable else END


def _after_retrieve(
    state: AskState, runtime: Runtime[AskContext]
) -> Literal["rerank", "generate", "__end__"]:
    if not state["candidates"]:
        return END  # nothing to ground on — don't call the model
    return "rerank" if runtime.context.rerank else "generate"


def build_graph():
    """Compile the ``/api/ask`` flow: gate → retrieve → rerank → generate, with
    early exits for a too-broad question and for an empty retrieval."""
    return (
        StateGraph(AskState, context_schema=AskContext)
        .add_node("gate", check_answerable)
        .add_node("retrieve", retrieve)
        .add_node("rerank", rerank)
        .add_node("generate", generate_answer)
        .add_conditional_edges(START, _enter, ["gate", "retrieve"])
        .add_conditional_edges("gate", _after_gate, ["retrieve", END])
        .add_conditional_edges("retrieve", _after_retrieve, ["rerank", "generate", END])
        .add_edge("rerank", "generate")
        .add_edge("generate", END)
        .compile()
    )


# Compiled once and shared; the graph itself holds no per-request state.
ask_graph = build_graph()
