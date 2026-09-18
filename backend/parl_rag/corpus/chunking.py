from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .parsing import Turn


@dataclass
class Chunk:
    """A retrievable unit of text plus everything we need to cite/filter it."""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    method: str = "unknown"

    # Filled in by the optional Contextual Retrieval step: an LLM-written prefix
    # that situates the chunk inside its transcript. ``embed_text`` is what we
    # actually embed/index (context + text); ``text`` stays clean for display.
    context: str | None = None

    @property
    def embed_text(self) -> str:
        return f"{self.context}\n\n{self.text}" if self.context else self.text

    # Convenience accessors used all over the codebase.
    @property
    def speaker(self) -> str | None:
        return self.metadata.get("speaker")

    @property
    def party(self) -> str | None:
        return self.metadata.get("party")

    @property
    def date(self) -> str | None:
        return self.metadata.get("date")


# --------------------------------------------------------------------------- #
# Windowed turns: merge tiny turns, split long ones
# --------------------------------------------------------------------------- #
def _turn_meta(turn: Turn) -> dict:
    return {
        "speaker": turn.speaker,
        "speaker_raw": turn.speaker_raw,
        "role": turn.role,
        "party": turn.party,
        "modifier": turn.modifier,
        "date": turn.date,
        "transcript_id": turn.transcript_id,
        "sitting": turn.sitting,
        "turn_index": turn.index,
    }


def chunk_by_turn_windowed(turns: Sequence[Turn], *, max_chars: int = 1200,
                           overlap_chars: int = 150,
                           min_words: int = 0) -> list[Chunk]:
    """Token-aware-ish structural chunking.

    Real debates have both 5-word interjections and 2000-word speeches. A pure
    one-chunk-per-turn index has wildly uneven chunk sizes. Here we:
      * split a long turn into multiple sub-chunks (with small overlap), and
      * keep short turns whole (we do NOT merge across speakers — that would
        mix two MPs in one chunk and destroy attribution).
    This is the pragmatic default.

    ``min_words`` drops turns below that length: one-line procedural chair turns
    ("Заповядайте.") embed degenerately and BM25 over-scores very short
    documents, so they pollute the hybrid candidate pool. 0 keeps everything.
    """
    chunks: list[Chunk] = []
    for turn in turns:
        if turn.word_count < min_words:
            continue
        meta = _turn_meta(turn)
        text = turn.text
        if len(text) <= max_chars:
            chunks.append(Chunk(
                id=f"{turn.transcript_id}:turn:{turn.index}",
                text=text, metadata=meta, method="turn_windowed",
            ))
            continue
        # Split the long speech on sentence boundaries, packing up to max_chars.
        for j, piece in enumerate(_pack_sentences(text, max_chars, overlap_chars)):
            chunks.append(Chunk(
                id=f"{turn.transcript_id}:turn:{turn.index}:{j}",
                text=piece,
                metadata={**meta, "subchunk": j},
                method="turn_windowed",
            ))
    return chunks


_SENT_RE = re.compile(r"(?<=[.!?…])\s+")

def _pack_sentences(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    sentences = _SENT_RE.split(text)
    out: list[str] = []

    buf = ""
    fresh = "" # does not includes the overlap chars

    for s in sentences:
        if  buf and len(buf) + len(s) + 1 > max_chars:  # we reached enough chars
            out.append(buf.strip())
            buf = (buf[-overlap_chars:] + " " + s) if overlap_chars else s
            fresh = s
        else:
            buf = f"{buf} {s}"
            fresh = f"{fresh} {s}"

    if fresh:
        if out and len(fresh) < 200:
            out[-1] = f"{out[-1]} {fresh}"
        else:
            out.append(buf.strip())

    return out
