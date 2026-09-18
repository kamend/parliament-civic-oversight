from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ..answering.graph import AskContext, ask_graph
from ..corpus import sittings as corpus_sittings
from ..retrieval.store import LanceDBStore
from ..settings import settings
from .deps import get_store
from .schemas import (
    AskRequest,
    FiltersResponse,
    HealthResponse,
    SittingsResponse,
    SourceItem,
    TranscriptResponse,
    TranscriptTurn,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Constructing the store is cheap: it opens nothing and loads no model until
    # first use. The warmup task below is what pays for the weights.
    app.state.store = LanceDBStore()
    # Set True once warmup finishes. Surfaced by /api/health so a load balancer
    # / the UI can tell "up" from "warm".
    app.state.models_warm = False

    async def _warm():
        try:
            await asyncio.to_thread(app.state.store.warm)
            app.state.models_warm = True
            print("models are warm..")
        except Exception as e:  # noqa: BLE001
            print(f"[startup] model warmup skipped: {e}")

    task = asyncio.create_task(_warm())
    yield
    task.cancel()


app = FastAPI(title="Parliament RAG", version="0.1.0", lifespan=lifespan)

# CORS — settings.cors_origin is a comma-separated origin list (frontend dev + prod).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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
def health(request: Request, store: LanceDBStore = Depends(get_store)) -> HealthResponse:
    """Readiness probe: confirms the store opens and reports row count + warmth."""
    rows = store.count()  # 0 (and status 'empty') if the table isn't built yet
    return HealthResponse(
        status="ok" if store.exists() else "empty",
        table=store.table_name,
        rows=rows,
        models_warm=request.app.state.models_warm,
        embed_model=settings.embed_model,
        rerank_model=settings.rerank_model,
        llm_model=settings.llm_model,
    )


@app.get("/api/filters", response_model=FiltersResponse)
def filters(store: LanceDBStore = Depends(get_store)) -> FiltersResponse:
    """Distinct parties / speakers and the date range, for the UI filter bar."""
    return FiltersResponse(**store.metadata_summary())


@app.get("/api/sittings", response_model=SittingsResponse)
def sittings() -> SittingsResponse:
    """Every plenary sitting on disk, newest first, plus the distinct months —
    powers the browse-all-sittings page and its month filter. Sitting-level
    metadata only; the full transcript is fetched per sitting via the endpoint
    below."""
    return SittingsResponse(**corpus_sittings.list_sittings())


@app.get("/api/transcript/{transcript_id}", response_model=TranscriptResponse)
def transcript(transcript_id: str) -> TranscriptResponse:
    """The full plenary sitting behind a citation, parsed into ordered turns.

    The frontend opens this in a full-screen viewer when you ask to see where a
    source came from, then scrolls to and highlights the cited ``turn_index``.
    404 if no transcript with that id is on disk.
    """
    tr = corpus_sittings.load_transcript_by_id(transcript_id)
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
def ask(req: AskRequest, store: LanceDBStore = Depends(get_store)) -> StreamingResponse:
    """Retrieve, then stream a grounded cited answer as SSE.

    Event sequence:
      ``sources`` → the reranked top-k turns (so the UI can render chips first),
      then ``token``* → answer fragments, then ``done`` → model + token usage.
    A too-broad question is short-circuited by the answerability gate: it emits a
    ``clarify`` event (soft message + suggested reformulations) and a terminal
    ``done`` instead, never touching retrieval or generation.
    On any failure mid-stream an ``error`` event is emitted instead of ``done``.

    The flow itself (gate → retrieve → rerank → generate) is the LangGraph graph
    in ``parl_rag.answering.graph``; this endpoint only translates its stream into SSE.

    A plain (sync) generator is used so FastAPI runs the blocking retrieval and
    the synchronous model stream in a worker thread, off the event loop.
    """
    context = AskContext(
        store=store,
        k=req.k,
        party=req.party,
        speaker=req.speaker,
        since=req.since,
        until=req.until,
        date=req.date,
        rerank=req.rerank,
        route=req.route,
    )

    def event_stream() -> Iterator[str]:
        # The graph reports progress as state updates; each SSE event keys off
        # the state field that just landed, not the node that wrote it.
        stage = "retrieval"  # which stage an exception belongs to
        try:
            for mode, payload in ask_graph.stream(
                {"question": req.question},
                context=context,
                stream_mode=["updates", "messages"],
            ):
                if mode == "messages":
                    chunk, meta = payload
                    # The gate's model streams too; only the answer is for the user.
                    if meta.get("langgraph_node") == "generate" and chunk.text:
                        yield _sse("token", {"text": chunk.text})
                    continue

                for update in payload.values():
                    update = update or {}
                    assessment = update.get("assessment")
                    if assessment is not None and not assessment.answerable:
                        yield _sse("clarify", {
                            "message": assessment.message,
                            "suggestions": assessment.suggestions,
                            "reason": assessment.reason,
                        })
                        yield _sse("done", {"answer": "", "needs_clarification": True})
                    if "hits" in update:
                        hits = update["hits"]
                        sources = [
                            SourceItem.from_hit(h, i).model_dump()
                            for i, h in enumerate(hits, start=1)
                        ]
                        yield _sse("sources", {"sources": sources})
                        if not hits:
                            # Nothing to ground on — the graph ends without calling the model.
                            yield _sse("done", {"answer": "", "no_results": True})
                        stage = "generation"
                    if "answer" in update:
                        yield _sse("done", {
                            "answer": update["answer"],
                            "model": update["model"],
                            "input_tokens": update["input_tokens"],
                            "output_tokens": update["output_tokens"],
                        })
        except (Exception, SystemExit) as e:  # noqa: BLE001 — incl. missing API key (SystemExit)
            yield _sse("error", {"stage": stage, "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
