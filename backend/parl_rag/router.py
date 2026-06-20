from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config
from .generate import get_client


@dataclass
class QueryAssessment:
    """The gate's verdict on one question.

    ``answerable`` is the only field the dispatch logic branches on. When it's
    False, ``message`` and ``suggestions`` carry the soft clarification shown to
    the user; when True they're empty and ignored. ``reason`` is a short English
    note for logs/debugging, never shown to the user.
    """

    answerable: bool
    reason: str = ""
    message: str | None = None
    suggestions: list[str] = field(default_factory=list)


# The retrieval system's capabilities and limits, spelled out so the classifier
# judges "can THIS pipeline answer it", not "is this a reasonable question".
SYSTEM_PROMPT = (
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
    "Output ONLY a single JSON object — no markdown code fences, no commentary "
    "before or after it. Do not answer the question itself; only classify it. "
    "The JSON has these keys:\n"
    '  "answerable": boolean,\n'
    '  "reason": short English explanation of the verdict,\n'
    '  "message": when answerable is false, a brief, polite message IN THE '
    "QUESTION'S LANGUAGE asking the user to ask something more specific and "
    "saying why; empty string when answerable is true,\n"
    '  "suggestions": when answerable is false, an array of up to 3 concrete, '
    "specific example questions IN THE QUESTION'S LANGUAGE that the user might "
    "have meant (e.g. about the budget, the euro, judicial reform); empty array "
    "when answerable is true."
)


def assess(question: str, *, model: str | None = None) -> QueryAssessment:
    """Classify whether ``question`` is specific enough for the retrieval pipeline.

    Returns a :class:`QueryAssessment`. **Never raises** — every failure path
    (missing key, provider error, malformed JSON) returns an *answerable* verdict
    so the gate degrades to a no-op rather than blocking a legitimate question.
    """
    question = (question or "").strip()
    if not question:
        # Empty input isn't the gate's problem; let the normal path handle it.
        return QueryAssessment(answerable=True, reason="empty question")

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=model or config.LLM_ROUTER_MODEL,
            max_tokens=400,
            temperature=0,                       # stable, deterministic verdicts
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )
        raw = resp.choices[0].message.content or ""
        return _parse(raw)
    except Exception as e:  # noqa: BLE001 — fail OPEN: a broken gate must not block
        return QueryAssessment(answerable=True, reason=f"router error: {e}")


def _extract_json(raw: str) -> dict | None:
    """Pull the JSON object out of a model response, tolerant of wrapping.

    Models routinely ignore "JSON only" and wrap the object in a ```json fence or
    surround it with prose (observed with Anthropic models via OpenRouter, which
    don't honor ``response_format``). We try a direct parse first, then fall back
    to the substring from the first ``{`` to the last ``}``. Returns the parsed
    dict, or None if nothing parses.
    """
    if not raw:
        return None
    raw = raw.strip()
    candidates = [raw]
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _parse(raw: str) -> QueryAssessment:
    """Parse the model's JSON into a :class:`QueryAssessment`, defensively.

    Anything we can't read as a clear *not-answerable* verdict resolves to
    answerable (fail open). Suggestions are coerced to a clean list of up to 3
    non-empty strings.
    """
    data = _extract_json(raw)
    if data is None:
        return QueryAssessment(answerable=True, reason="unparseable router output")

    answerable = bool(data.get("answerable", True))
    reason = str(data.get("reason") or "")
    if answerable:
        return QueryAssessment(answerable=True, reason=reason)

    message = data.get("message")
    message = str(message).strip() if message else None
    raw_suggestions = data.get("suggestions") or []
    suggestions: list[str] = []
    if isinstance(raw_suggestions, list):
        for s in raw_suggestions:
            text = str(s).strip()
            if text:
                suggestions.append(text)
            if len(suggestions) == 3:
                break

    return QueryAssessment(
        answerable=False,
        reason=reason,
        message=message,
        suggestions=suggestions,
    )
