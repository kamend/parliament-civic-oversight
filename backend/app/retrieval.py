from __future__ import annotations

import json
from pathlib import Path

from parl_rag import config
from parl_rag.parsing import Transcript, has_turns, load_transcript
from parl_rag.store import LanceDBStore, SearchHit

# Unpublished sittings carry only parliament.bg's ~700-byte "published within 7
# days" notice; a real transcript is hundreds of KB. We stat the file and only
# read the small ones to confirm — large files are certainly real transcripts.
_PLACEHOLDER_MAX_BYTES = 2000

# Process-wide singleton. Built lazily (or eagerly at startup via warm()) and
# reused for every request — never per-request, or every query would reload GBs
# of model weights.
_store: LanceDBStore | None = None


def get_store() -> LanceDBStore:
    """Return the shared store, constructing it on first use."""
    global _store
    if _store is None:
        _store = LanceDBStore()
    return _store


def warm(*, with_rerank: bool = True) -> None:
    """Eagerly load the models so the first real query isn't slow.

    ``store.load_embedder()`` loads the bge-m3 embedder; instantiating the
    reranker loads bge-reranker-v2-m3. Called from the app's startup lifespan so
    the cost is paid once, before traffic, not on the first user's request.
    """
    store = get_store()
    store.load_embedder()
    if with_rerank:
        _ = store.reranker      # forces the cross-encoder to load


def load_transcript_by_id(transcript_id: str) -> Transcript | None:
    """Load a full sitting by its transcript id, parsed into ordered turns.

    Transcripts live on disk as ``data/transcripts/<YYYY-MM>/<date>_<id>.txt``;
    the id alone is unique, so we glob for the matching ``.txt`` (the sibling
    ``.json`` is picked up by :func:`load_transcript` for the sitting header).
    Returns ``None`` if no file matches, so the API can answer 404.
    """
    # Guard against path traversal / odd ids: transcript ids are bare integers.
    if not transcript_id.isdigit():
        return None
    matches = sorted(config.DATA_DIR.glob(f"*/*_{transcript_id}.txt"))
    if not matches:
        return None
    return load_transcript(Path(matches[0]))


def _has_transcript(txt_path: Path) -> bool:
    """Whether a sitting's transcript is actually published (vs. a placeholder).

    Cheap by design: a real transcript is far larger than the placeholder notice,
    so we trust size and only read the small files to confirm they parse to turns.
    """
    try:
        if txt_path.stat().st_size > _PLACEHOLDER_MAX_BYTES:
            return True
        return has_turns(txt_path.read_text(encoding="utf-8"))
    except OSError:
        return False


def list_sittings() -> dict:
    """Catalog every plenary sitting on disk, newest first, for the browse page.

    This is a sitting-level listing, not a turn search — its source of truth is
    the filesystem, not LanceDB (which holds chunked turns). We key off the
    ``.txt`` files so every listed sitting is one ``/api/transcript`` can open,
    and read the sibling ``.json`` only for the human title (``Pl_Sten_sub``) and
    the authoritative date. Each sitting also carries ``has_transcript`` — False
    for the most recent sittings whose stenographic protocol isn't published yet.
    The corpus is small (tens of sittings) so a full scan per request is cheap;
    add an in-process cache here if it ever isn't.
    """
    sittings: list[dict] = []
    for txt_path in sorted(config.DATA_DIR.glob("*/*.txt")):
        date, _, tid = txt_path.stem.partition("_")  # "2026-05-22_11129"
        title: str | None = None
        json_path = txt_path.with_suffix(".json")
        if json_path.exists():
            try:
                meta = json.loads(json_path.read_text(encoding="utf-8"))
                date = meta.get("Pl_Sten_date", date) or date
                title = (meta.get("Pl_Sten_sub") or "").strip() or None
            except (json.JSONDecodeError, OSError):
                pass
        sittings.append({
            "id": tid,
            "date": date,
            "month": date[:7],
            "title": title,
            "has_transcript": _has_transcript(txt_path),
        })

    # Newest first; id breaks ties when two sittings share a date.
    sittings.sort(key=lambda s: (s["date"], s["id"]), reverse=True)
    months = sorted({s["month"] for s in sittings}, reverse=True)
    return {"sittings": sittings, "months": months}


def hit_to_source(hit: SearchHit, n: int) -> dict:
    """Flatten a ``SearchHit`` into the wire ``SourceItem`` dict.

    ``n`` is the 1-based position in the reranked list — the number the answer
    cites as ``[S{n}]`` and the frontend keys its source chips on.
    """
    c = hit.chunk
    m = c.metadata
    return {
        "n": n,
        "id": c.id,
        "text": c.text,
        "speaker": c.speaker,
        "speaker_raw": m.get("speaker_raw"),
        "role": m.get("role"),
        "party": c.party,
        "date": c.date,
        "transcript_id": m.get("transcript_id"),
        "sitting": m.get("sitting"),
        "turn_index": m.get("turn_index"),
        "score": hit.score,
        "hybrid_score": hit.hybrid_score,
        "reranked": hit.reranked,
        "prior_rank": hit.prior_rank,
    }
