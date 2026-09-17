from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

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
# 1. Fixed-size character chunking (the naive baseline)
# --------------------------------------------------------------------------- #
def chunk_fixed(text: str, *, size: int = 1000, overlap: int = 150,
                base_meta: dict | None = None, source_id: str = "doc") -> list[Chunk]:
    """Slice text into overlapping fixed-size windows.

    Pros: trivial, works on any text. Cons: cuts mid-sentence and mid-speaker, so
    a single chunk can mix two MPs — destroying attribution. Easy to criticize,
    not what you'd ship here.
    """
    base_meta = base_meta or {}
    chunks: list[Chunk] = []
    step = max(1, size - overlap)
    for i, start in enumerate(range(0, max(1, len(text)), step)):
        piece = text[start:start + size].strip()
        if not piece:
            continue
        chunks.append(Chunk(
            id=f"{source_id}:fixed:{i}",
            text=piece,
            metadata={**base_meta, "char_start": start, "char_end": start + len(piece)},
            method="fixed",
        ))
    return chunks


# --------------------------------------------------------------------------- #
# 2. Structural chunking: one chunk per speaker turn
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


def chunk_by_turn(turns: Sequence[Turn], *, min_words: int = 0) -> list[Chunk]:
    """One chunk per speaker turn. The natural, attribution-preserving unit.

    ``min_words`` drops procedural one-liners ("Заповядайте.") if you want a
    cleaner index; keep 0 to retain everything.
    """
    chunks: list[Chunk] = []
    for turn in turns:
        if turn.word_count < min_words:
            continue
        chunks.append(Chunk(
            id=f"{turn.transcript_id}:turn:{turn.index}",
            text=turn.text,
            metadata=_turn_meta(turn),
            method="turn",
        ))
    return chunks


# --------------------------------------------------------------------------- #
# 3. Windowed turns: merge tiny turns, split long ones
# --------------------------------------------------------------------------- #
def chunk_by_turn_windowed(turns: Sequence[Turn], *, max_chars: int = 1200,
                           overlap_chars: int = 150,
                           min_words: int = 0) -> list[Chunk]:
    """Token-aware-ish structural chunking.

    Real debates have both 5-word interjections and 2000-word speeches. A pure
    one-chunk-per-turn index has wildly uneven chunk sizes. Here we:
      * split a long turn into multiple sub-chunks (with small overlap), and
      * keep short turns whole (we do NOT merge across speakers — that would
        reintroduce the attribution problem from fixed chunking).
    This is the pragmatic default.

    ``min_words`` drops turns below that length, same as in ``chunk_by_turn``:
    one-line procedural chair turns ("Заповядайте.") embed degenerately and BM25
    over-scores very short documents, so they pollute the hybrid candidate pool.
    0 keeps everything.
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


# --------------------------------------------------------------------------- #
# 4. Semantic chunking: split where the topic (embedding) shifts
# --------------------------------------------------------------------------- #
def chunk_semantic(text: str, embed_fn: Callable[[list[str]], "object"], *,
                   base_meta: dict | None = None, source_id: str = "doc",
                   threshold_percentile: float = 90.0,
                   max_chars: int = 1500) -> list[Chunk]:
    """Split text where consecutive sentences become semantically dissimilar.

    Idea (Greg Kamradt's "semantic chunking"): embed each sentence, walk the
    sequence, and start a new chunk wherever the cosine *distance* between
    neighbours jumps above a high percentile — i.e. the topic changed. This keeps
    semantically coherent text together regardless of length.

    Costs an embedding pass at index time and is finicky to tune, which is why
    structural chunking usually wins for *structured* documents like transcripts.
    Included so the tradeoff can be measured directly.

    ``embed_fn`` takes a list[str] and returns an (n, d) numpy array (use
    ``parl_rag.embeddings.Embedder.encode``).
    """
    import numpy as np

    base_meta = base_meta or {}
    sentences = [s.strip() for s in _SENT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        return [Chunk(id=f"{source_id}:sem:0", text=text.strip(),
                      metadata=dict(base_meta), method="semantic")] if text.strip() else []

    vecs = np.asarray(embed_fn(sentences), dtype=np.float32)
    vecs /= (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)
    # distance between neighbouring sentences (1 - cosine similarity)
    dists = 1.0 - np.sum(vecs[:-1] * vecs[1:], axis=1)
    cut = np.percentile(dists, threshold_percentile)
    breakpoints = {i + 1 for i, d in enumerate(dists) if d > cut}

    chunks: list[Chunk] = []
    buf: list[str] = []
    n = 0

    def flush() -> None:
        nonlocal buf, n
        if buf:
            chunks.append(Chunk(id=f"{source_id}:sem:{n}", text=" ".join(buf).strip(),
                                metadata=dict(base_meta), method="semantic"))
            n += 1
            buf = []

    for i, sent in enumerate(sentences):
        if i in breakpoints or sum(len(s) for s in buf) + len(sent) > max_chars:
            flush()
        buf.append(sent)
    flush()
    return chunks
