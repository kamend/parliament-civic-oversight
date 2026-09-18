from __future__ import annotations

from typing import Sequence

from ..corpus.chunking import Chunk

# --------------------------------------------------------------------------- #
# Answer generation (the graph's generate node)
# --------------------------------------------------------------------------- #
# System rules for the grounded, cited answer. Governs attribution, citation
# format, and refusal-when-unsupported behavior.
ANSWER_SYSTEM_PROMPT = (
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

# The user turn: numbered source blocks, then the question + cite rule.
# Fields: {sources}, {question}.
ANSWER_USER_TEMPLATE = (
    "Sources from parliamentary transcripts:\n\n{sources}\n\n"
    "---\nQuestion: {question}\n\n"
    "Answer using only the sources above, with [S#] citations and "
    "speaker/party/date attribution."
)

# --------------------------------------------------------------------------- #
# Answerability gate (answering/gate.py)
# --------------------------------------------------------------------------- #
# The retrieval system's capabilities and limits, spelled out so the classifier
# judges "can THIS pipeline answer it", not "is this a reasonable question".
ROUTER_SYSTEM_PROMPT = (
    "You are a query gate for a retrieval system over Bulgarian Parliament "
    "plenary transcripts. The system answers a question by semantically matching "
    "it to INDIVIDUAL speaker turns — what was said about a specific topic, bill, "
    "policy, event, argument, or by/about a specific person. It then writes a "
    "grounded, cited answer from the few best-matching turns.\n\n"
    "It therefore CANNOT answer broad, open-ended, or whole-sitting OVERVIEW "
    "questions that have no specific topical anchor to match against — e.g. "
    "'За какво говориха депутатите днес?', 'Какво стана в парламента?', 'Разкажи "
    "ми за заседанието'. These ask to summarize an entire sitting/day; matching "
    "them returns near-random turns, so they must be sent back for refinement.\n\n"
    "Classify the user's question, and LEAN TOWARDS ANSWERABLE. A question is "
    "ANSWERABLE when it names or clearly implies a concrete topic, bill, policy "
    "area, institution, event, argument, or person that statements can be "
    "retrieved for. A SINGLE named topic is a sufficient anchor even if it could "
    "be narrower — do NOT demand a specific sub-aspect, bill number, speaker, or "
    "date. For example 'Как се обсъждаше реформата в съдебната система?' "
    "(anchor: съдебна реформа) and 'Какво беше казано за бюджета?' (anchor: "
    "бюджет) are both ANSWERABLE.\n\n"
    "Mark NOT answerable ONLY when the question has NO topical anchor at all: a "
    "broad overview / temporal aggregate of a whole sitting or day ('За какво "
    "говориха депутатите днес?', 'Какво стана в парламента?', 'Разкажи ми за "
    "заседанието'), or wording so vague it could be about anything. A filter "
    "like a party, speaker, or date does NOT by itself turn an anchorless "
    "question into a specific one.\n\n"
    # The output shape lives on gate.QueryAssessment: its field descriptions
    # are sent as the tool schema, so they aren't repeated here.
    "Do not answer the question itself; only classify it, and report the "
    "verdict by calling the provided tool."
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


def build_messages(question: str, chunks: Sequence[Chunk]) -> list[tuple[str, str]]:
    """The chat messages for the answer model: the system rules, then the
    numbered source blocks with the question + cite rule."""
    return [
        ("system", ANSWER_SYSTEM_PROMPT),
        ("user", ANSWER_USER_TEMPLATE.format(sources=format_sources(chunks), question=question)),
    ]
