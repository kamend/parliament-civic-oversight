"""The ask graph's routing and streaming, with the store and both models faked
so nothing is loaded from disk and no API is called."""
from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from parl_rag import graph, llm, router
from parl_rag.chunking import Chunk
from parl_rag.graph import AskContext, ask_graph
from parl_rag.router import QueryAssessment
from parl_rag.store import SearchHit


def _hit(i: int) -> SearchHit:
    chunk = Chunk(id=f"c{i}", text=f"text {i}", metadata={
        "speaker": "Иван Иванов", "party": "X", "date": "2026-05-22",
    })
    return SearchHit(chunk=chunk, score=1.0 / i, hybrid_score=1.0 / i, reranked=False)


class FakeStore:
    def __init__(self, n_candidates: int):
        self.n = n_candidates
        self.reranked = False

    def hybrid_search(self, question, *, k, rerank, **filters):
        return [_hit(i) for i in range(1, self.n + 1)][: (self.n if rerank else k)]

    def rerank_hits(self, question, candidates, *, k):
        self.reranked = True
        return list(reversed(candidates))[:k]


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    monkeypatch.setattr(
        llm, "answer_model",
        lambda: GenericFakeChatModel(messages=iter([AIMessage(content="Отговор [S1].")])),
    )
    monkeypatch.setattr(router, "assess", lambda q: QueryAssessment(answerable=True))


def test_full_path_reranks_then_answers():
    store = FakeStore(n_candidates=4)
    out = ask_graph.invoke({"question": "бюджет"}, context=AskContext(store=store, k=2))
    assert store.reranked
    assert [h.chunk.id for h in out["hits"]] == ["c4", "c3"]
    assert out["answer"] == "Отговор [S1]."


def test_rerank_off_skips_the_rerank_node():
    store = FakeStore(n_candidates=4)
    out = ask_graph.invoke(
        {"question": "бюджет"}, context=AskContext(store=store, k=2, rerank=False)
    )
    assert not store.reranked
    assert [h.chunk.id for h in out["hits"]] == ["c1", "c2"]
    assert out["answer"]


def test_unanswerable_question_stops_at_the_gate(monkeypatch):
    verdict = QueryAssessment(answerable=False, message="По-конкретно?", suggestions=["a"])
    monkeypatch.setattr(router, "assess", lambda q: verdict)
    out = ask_graph.invoke({"question": "какво стана"}, context=AskContext(store=FakeStore(4)))
    assert out["assessment"] is verdict
    assert "candidates" not in out and "answer" not in out


def test_route_off_skips_the_gate(monkeypatch):
    monkeypatch.setattr(router, "assess", lambda q: pytest.fail("gate should not run"))
    out = ask_graph.invoke(
        {"question": "бюджет"}, context=AskContext(store=FakeStore(4), route=False)
    )
    assert "assessment" not in out and out["answer"]


def test_no_rows_ends_without_calling_the_model(monkeypatch):
    monkeypatch.setattr(llm, "answer_model", lambda: pytest.fail("model should not run"))
    out = ask_graph.invoke({"question": "бюджет"}, context=AskContext(store=FakeStore(0)))
    assert out["hits"] == [] and "answer" not in out


def test_answer_tokens_stream_from_the_generate_node():
    tokens = [
        chunk.text
        for mode, payload in ask_graph.stream(
            {"question": "бюджет"}, context=AskContext(store=FakeStore(4)),
            stream_mode=["updates", "messages"],
        )
        if mode == "messages"
        for chunk, meta in [payload]
        if meta.get("langgraph_node") == "generate"
    ]
    assert len(tokens) > 1 and "".join(tokens) == "Отговор [S1]."


def test_suggestions_are_cleaned_and_capped():
    v = QueryAssessment(answerable=False, message="  ", suggestions=[" a ", "", "b", "c", "d"])
    assert v.message is None and v.suggestions == ["a", "b", "c"]
