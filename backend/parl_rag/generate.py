from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Iterator, Sequence

from . import config
from .chunking import Chunk


@functools.lru_cache(maxsize=1)
def get_client():
    """Lazily build an OpenAI client pointed at OpenRouter, with a friendly error
    if unconfigured."""
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "The 'openai' package is required for generation. "
            "Install deps with:  uv sync   (or  pip install openai)"
        ) from e
    if not config.OPENROUTER_API_KEY:
        raise SystemExit(
            "No OPENROUTER_API_KEY found. Either create backend/.env with:\n"
            "    OPENROUTER_API_KEY=sk-or-...\n"
            "(copy .env.example to .env), or export OPENROUTER_API_KEY in your shell.\n"
            "Get a key at https://openrouter.ai/keys."
        )
    return OpenAI(
        base_url=config.OPENROUTER_BASE_URL,
        api_key=config.OPENROUTER_API_KEY,
        # Optional attribution on OpenRouter's dashboards / leaderboards.
        default_headers={
            "HTTP-Referer": config.OPENROUTER_SITE_URL,
            "X-Title": config.OPENROUTER_APP_TITLE,
        },
    )


# --------------------------------------------------------------------------- #
# Context assembly
# --------------------------------------------------------------------------- #
def format_sources(chunks: Sequence[Chunk]) -> str:
    """Render chunks as numbered, attributed source blocks for the prompt."""
    blocks = []
    for i, c in enumerate(chunks, start=1):
        who = c.speaker or "неизвестен говорител"
        party = f", {c.party}" if c.party else ""
        date = c.date or "?"
        role = f" [{c.metadata.get('role')}]" if c.metadata.get("role") else ""
        blocks.append(f"[S{i}] ({who}{party}{role}, {date})\n{c.text.strip()}")
    return "\n\n".join(blocks)


SYSTEM_PROMPT = (
    "You are a careful research assistant for the Bulgarian Parliament. "
    "You answer questions strictly from the provided transcript excerpts (sources). "
    "Rules:\n"
    "1. Use ONLY the information in the sources. Never rely on outside knowledge.\n"
    "2. Always attribute statements: say WHO said it (name + party) and WHEN (date).\n"
    "3. Cite every claim with the source tag, e.g. [S2].\n"
    "4. If the sources do not contain the answer, say so plainly — do not guess.\n"
    "5. Answer in the same language as the question (Bulgarian questions get "
    "Bulgarian answers)."
)


@dataclass
class AnswerResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


def _build_user_prompt(question: str, chunks: Sequence[Chunk]) -> str:
    """The user turn: the numbered source blocks, then the question + cite rule.
    Shared by the blocking and streaming generators so the prompt can't drift."""
    sources = format_sources(chunks)
    return (
        f"Sources from parliamentary transcripts:\n\n{sources}\n\n"
        f"---\nQuestion: {question}\n\n"
        f"Answer using only the sources above, with [S#] citations and "
        f"speaker/party/date attribution."
    )


def _build_messages(question: str, chunks: Sequence[Chunk]) -> list[dict]:
    """OpenAI-style message list: the system rules, then the sources + question."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(question, chunks)},
    ]


def answer(question: str, chunks: Sequence[Chunk], *, model: str | None = None,
           max_tokens: int = 1024) -> AnswerResult:
    """Generate a grounded, cited answer from the retrieved chunks."""
    client = get_client()
    model = model or config.LLM_MODEL
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=_build_messages(question, chunks),
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return AnswerResult(
        text=text, model=resp.model or model,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )


def stream_answer(
    question: str, chunks: Sequence[Chunk], *,
    model: str | None = None, max_tokens: int = 4096,
) -> Iterator[tuple[str, object]]:
    """Stream a grounded, cited answer, for the SSE ``/api/ask`` endpoint.

    Yields ``("token", text_delta)`` for each streamed text fragment as the model
    writes the answer, then a single terminal ``("usage", AnswerResult)`` once the
    stream closes (the full text plus token counts). The two-kind tuple keeps the
    transport (SSE framing) in the API layer and the model call here.

    ``stream_options={"include_usage": True}`` asks OpenRouter to append a final
    chunk carrying token usage (it has no choices/content of its own).
    """
    client = get_client()
    model = model or config.LLM_MODEL
    stream = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=_build_messages(question, chunks),
        stream=True,
        stream_options={"include_usage": True},
    )
    parts: list[str] = []
    final_model = model
    in_tok = out_tok = 0
    for chunk in stream:
        if chunk.model:
            final_model = chunk.model
        if chunk.choices:
            piece = chunk.choices[0].delta.content
            if piece:
                parts.append(piece)
                yield "token", piece
        if chunk.usage:  # the trailing usage-only chunk
            in_tok = chunk.usage.prompt_tokens
            out_tok = chunk.usage.completion_tokens
    yield "usage", AnswerResult(
        text="".join(parts), model=final_model,
        input_tokens=in_tok, output_tokens=out_tok,
    )


# --------------------------------------------------------------------------- #
# Contextual Retrieval: generate a situating prefix per chunk
# --------------------------------------------------------------------------- #
CONTEXT_PROMPT = (
    "Here is a chunk we want to situate within the whole transcript so it can be "
    "retrieved on its own:\n<chunk>\n{chunk}\n</chunk>\n\n"
    "Give a short, succinct context (1-2 sentences, same language as the chunk) "
    "that situates this chunk within the sitting: what is being debated, who is "
    "speaking and their party if known, and the date. Answer ONLY with the context."
)


def generate_chunk_context(chunk_text: str, full_document: str, *,
                           model: str | None = None) -> tuple[str, dict]:
    """'Contextual Retrieval': write a context prefix for one chunk.

    The full transcript is sent as a cached prefix via a ``cache_control``
    breakpoint, so across the many chunks of one transcript you pay to read the
    document once and get cheap cache reads thereafter — this is what makes
    contextual retrieval affordable. OpenRouter forwards ``cache_control`` to
    providers that support prompt caching (e.g. Anthropic); for providers that
    cache automatically (e.g. OpenAI) it's harmless, and for the rest it's
    ignored. Returns (context_text, usage_dict).
    """
    client = get_client()
    model = model or config.LLM_CONTEXT_MODEL  # cheap model is fine for this
    resp = client.chat.completions.create(
        model=model,
        max_tokens=200,
        messages=[
            {"role": "system", "content": [{
                "type": "text",
                "text": f"<document>\n{full_document}\n</document>",
                "cache_control": {"type": "ephemeral"},  # cache the whole transcript
            }]},
            {"role": "user", "content": CONTEXT_PROMPT.format(chunk=chunk_text)},
        ],
    )
    ctx = (resp.choices[0].message.content or "").strip()
    u = resp.usage
    details = getattr(u, "prompt_tokens_details", None) if u else None
    usage = {
        "input_tokens": u.prompt_tokens if u else 0,
        "cache_read": getattr(details, "cached_tokens", 0) or 0,
        "cache_write": 0,  # not separately reported in the OpenAI-compatible usage
        "output_tokens": u.completion_tokens if u else 0,
    }
    return ctx, usage
