from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# /api/ask  — request
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    """Body of ``POST /api/ask``. Only ``question`` is required; the rest are the
    optional filter bar + retrieval knobs."""

    question: str = Field(..., min_length=1, description="The user's question (Cyrillic is fine).")
    party: Optional[str] = Field(None, description="Exact party filter, e.g. 'ВЪЗРАЖДАНЕ'.")
    speaker: Optional[str] = Field(None, description="Exact speaker display-name filter.")
    since: Optional[str] = Field(None, description="From this date inclusive, 'YYYY-MM-DD'.")
    until: Optional[str] = Field(None, description="Up to this date inclusive, 'YYYY-MM-DD'.")
    date: Optional[str] = Field(None, description="Single day, 'YYYY-MM-DD'.")
    k: int = Field(5, ge=1, le=25, description="Number of sources to ground on.")
    rerank: bool = Field(True, description="Run the cross-encoder rerank (slower, better).")
    route: bool = Field(
        True,
        description="Run the answerability gate first; if the question is too "
        "broad to ground, return a clarification instead of retrieving.",
    )


# --------------------------------------------------------------------------- #
# /api/ask  — the `sources` SSE event payload
# --------------------------------------------------------------------------- #
class SourceItem(BaseModel):
    """One retrieved turn, as the frontend renders it behind an ``[S#]`` chip."""

    n: int = Field(..., description="1-based source number, matches the [S#] tag.")
    id: str
    text: str
    speaker: Optional[str] = None
    speaker_raw: Optional[str] = None
    role: Optional[str] = None
    party: Optional[str] = None
    date: Optional[str] = None
    transcript_id: Optional[str] = None
    sitting: Optional[str] = None
    turn_index: Optional[int] = None
    # Scores, so the UI can show why a turn ranked where it did.
    score: float
    hybrid_score: float
    reranked: bool
    prior_rank: Optional[int] = None


# --------------------------------------------------------------------------- #
# /api/transcript/{transcript_id}
# --------------------------------------------------------------------------- #
class TranscriptTurn(BaseModel):
    """One speaker turn, as the full-transcript viewer renders it. ``index`` is
    the 0-based position within the sitting — the same value a ``SourceItem``
    carries as ``turn_index``, so the viewer can scroll to and highlight the turn
    a citation came from."""

    index: int
    speaker: str
    speaker_raw: str
    role: Optional[str] = None
    party: Optional[str] = None
    modifier: Optional[str] = None
    text: str


class TranscriptResponse(BaseModel):
    """A full daily plenary sitting, parsed into ordered speaker turns. Powers
    the full-screen transcript viewer opened from a source card."""

    id: str
    date: str
    header: str
    sitting: Optional[str] = None
    # False when the sitting's stenographic protocol isn't published yet — the
    # file holds only parliament.bg's placeholder notice, so there are no turns.
    has_transcript: bool = True
    turns: list[TranscriptTurn]


# --------------------------------------------------------------------------- #
# /api/sittings
# --------------------------------------------------------------------------- #
class SittingItem(BaseModel):
    """One plenary sitting, as the browse list renders it. Sitting-level metadata
    only (no turns) — the full record is fetched on demand via /api/transcript."""

    id: str = Field(..., description="Transcript id (Pl_Sten_id), unique per sitting.")
    date: str = Field(..., description="Sitting date, 'YYYY-MM-DD'.")
    month: str = Field(..., description="'YYYY-MM', for the month filter.")
    title: Optional[str] = Field(None, description="The Pl_Sten_sub header (assembly/sitting no.).")
    has_transcript: bool = Field(
        True, description="False when the stenographic protocol isn't published yet."
    )


class SittingsResponse(BaseModel):
    """Every sitting on disk, newest first, plus the distinct months for the
    browse page's month filter."""

    sittings: list[SittingItem]
    months: list[str] = Field(default_factory=list, description="Distinct 'YYYY-MM', newest first.")


# --------------------------------------------------------------------------- #
# /api/health
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    status: str = Field(..., description="'ok' once the table is reachable.")
    table: str
    rows: int
    models_warm: bool = Field(..., description="True once embed + rerank models are loaded.")
    embed_model: str
    rerank_model: str
    llm_model: str = Field(..., description="OpenRouter slug used for generation.")


# --------------------------------------------------------------------------- #
# /api/filters
# --------------------------------------------------------------------------- #
class FiltersResponse(BaseModel):
    """Distinct values that populate the UI filter bar."""

    parties: list[str]
    speakers: list[str]
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    # Distinct 'YYYY-MM-DD' dates that actually have sittings, so the date picker
    # can mark which days the corpus covers (vs. days with no plenary record).
    sitting_dates: list[str] = Field(default_factory=list)
