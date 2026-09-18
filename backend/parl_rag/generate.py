from __future__ import annotations

from typing import Sequence

from . import prompts
from .chunking import Chunk


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


def build_messages(question: str, chunks: Sequence[Chunk]) -> list[tuple[str, str]]:
    """The chat messages for the answer model: the system rules, then the
    numbered source blocks with the question + cite rule."""
    sources = format_sources(chunks)
    return [
        ("system", prompts.ANSWER_SYSTEM_PROMPT),
        ("user", prompts.ANSWER_USER_TEMPLATE.format(sources=sources, question=question)),
    ]
