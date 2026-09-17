from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Iterator
import asyncio


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from parl_rag import config, generate, router

from . import retrieval
from .schemas import (
    AskRequest,
    FiltersResponse,
    HealthResponse,
    SittingsResponse,
    TranscriptResponse,
    TranscriptTurn,
)

# Set True once the startup lifespan finishes loading the models. Surfaced by
# /api/health so a load balancer / the UI can tell "up" from "warm".
_MODELS_WARM = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    async def _warm():
        global _MODELS_WARM
        try:
            print("warming up models")
            await asyncio.to_thread(retrieval.warm)
            _MODELS_WARM = True
            print("models are warm..")
        except Exception as e:  # noqa: BLE001
            print(f"[startup] model warmup skipped: {e}")

    task = asyncio.create_task(_warm())
    yield
    task.cancel()


app = FastAPI(title="Parliament RAG", version="0.1.0", lifespan=lifespan)

# CORS — config.CORS_ORIGIN is a comma-separated origin list (frontend dev + prod).
_origins = [o.strip() for o in config.CORS_ORIGIN.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# SSE helpers
# --------------------------------------------------------------------------- #
def _sse(event: str, data: dict) -> str:
    """Frame one Server-Sent Event. ``ensure_ascii=False`` keeps Cyrillic intact
    over the UTF-8 response stream."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Readiness probe: confirms the store opens and reports row count + warmth."""
    store = retrieval.get_store()
    rows = store.count()  # 0 (and status 'empty') if the table isn't built yet
    return HealthResponse(
        status="ok" if store.exists() else "empty",
        table=store.table_name,
        rows=rows,
        models_warm=_MODELS_WARM,
        embed_model=config.EMBED_MODEL,
        rerank_model=config.RERANK_MODEL,
        llm_model=config.LLM_MODEL,
    )


@app.get("/api/filters", response_model=FiltersResponse)
def filters() -> FiltersResponse:
    """Distinct parties / speakers and the date range, for the UI filter bar."""
    return FiltersResponse(**retrieval.get_store().metadata_summary())


@app.get("/api/sittings", response_model=SittingsResponse)
def sittings() -> SittingsResponse:
    """Every plenary sitting on disk, newest first, plus the distinct months —
    powers the browse-all-sittings page and its month filter. Sitting-level
    metadata only; the full transcript is fetched per sitting via the endpoint
    below."""
    return SittingsResponse(**retrieval.list_sittings())


@app.get("/api/transcript/{transcript_id}", response_model=TranscriptResponse)
def transcript(transcript_id: str) -> TranscriptResponse:
    """The full plenary sitting behind a citation, parsed into ordered turns.

    The frontend opens this in a full-screen viewer when you ask to see where a
    source came from, then scrolls to and highlights the cited ``turn_index``.
    404 if no transcript with that id is on disk.
    """
    tr = retrieval.load_transcript_by_id(transcript_id)
    if tr is None:
        raise HTTPException(status_code=404, detail=f"Стенограма {transcript_id} не е открита.")
    return TranscriptResponse(
        id=tr.id,
        date=tr.date,
        header=tr.header,
        sitting=tr.turns[0].sitting if tr.turns else None,
        # No parsed turns ⇒ only the placeholder notice is on disk: not yet published.
        has_transcript=bool(tr.turns),
        turns=[
            TranscriptTurn(
                index=t.index,
                speaker=t.speaker,
                speaker_raw=t.speaker_raw,
                role=t.role,
                party=t.party,
                modifier=t.modifier,
                text=t.text,
            )
            for t in tr.turns
        ],
    )


@app.post("/api/ask")
def ask(req: AskRequest) -> StreamingResponse:
    """Retrieve, then stream a grounded cited answer as SSE.

    Event sequence:
      ``sources`` → the reranked top-k turns (so the UI can render chips first),
      then ``token``* → answer fragments, then ``done`` → model + token usage.
    A too-broad question is short-circuited by the answerability gate: it emits a
    ``clarify`` event (soft message + suggested reformulations) and a terminal
    ``done`` instead, never touching retrieval or generation.
    On any failure mid-stream an ``error`` event is emitted instead of ``done``.

    A plain (sync) generator is used so FastAPI runs the blocking retrieval and
    the synchronous Anthropic stream in a worker thread, off the event loop.
    """
    store = retrieval.get_store()

    def event_stream() -> Iterator[str]:
        # Answerability gate: a too-broad question ("За какво говориха днес?") has
        # no semantic anchor for the chunks, so grounding it would just confabulate.
        # Ask the user to narrow instead. The gate fails open (router.assess never
        # raises), so a router outage simply falls through to normal retrieval.
        if req.route:
            assessment = router.assess(req.question)
            if not assessment.answerable:
                yield _sse("clarify", {
                    "message": assessment.message,
                    "suggestions": assessment.suggestions,
                    "reason": assessment.reason,
                })
                yield _sse("done", {"answer": "", "needs_clarification": True})
                return

        try:
            hits = store.search(
                req.question,
                k=req.k,
                party=req.party,
                speaker=req.speaker,
                since=req.since,
                until=req.until,
                date=req.date,
                rerank=req.rerank,
            )
        except Exception as e:  # noqa: BLE001 — surface retrieval errors to the client
            yield _sse("error", {"stage": "retrieval", "message": str(e)})
            return

        sources = [retrieval.hit_to_source(h, i) for i, h in enumerate(hits, start=1)]
        yield _sse("sources", {"sources": sources})

        if not hits:
            # Nothing to ground on — don't call the model, just close cleanly.
            yield _sse("done", {"answer": "", "no_results": True})
            return

        chunks = [h.chunk for h in hits]
        try:
            for kind, payload in generate.stream_answer(req.question, chunks):
                if kind == "token":
                    yield _sse("token", {"text": payload})
                else:  # ("usage", AnswerResult)
                    yield _sse("done", {
                        "answer": payload.text,
                        "model": payload.model,
                        "input_tokens": payload.input_tokens,
                        "output_tokens": payload.output_tokens,
                    })
        except (Exception, SystemExit) as e:  # noqa: BLE001 — incl. missing API key (SystemExit)
            yield _sse("error", {"stage": "generation", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
