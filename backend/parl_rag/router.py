from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from . import llm, prompts


class QueryAssessment(BaseModel):
    """The gate's verdict on one question.

    ``answerable`` is the only field the dispatch logic branches on. When it's
    False, ``message`` and ``suggestions`` carry the soft clarification shown to
    the user; when True they're empty and ignored. ``reason`` is a short English
    note for logs/debugging, never shown to the user.

    Doubles as the tool schema the router model fills in, so the field
    descriptions below are part of the prompt.
    """

    answerable: bool = Field(
        True, description="Whether the retrieval pipeline can answer the question."
    )
    reason: str = Field("", description="Short English explanation of the verdict.")
    message: str | None = Field(
        None,
        description="When answerable is false, a brief, polite message IN THE "
        "QUESTION'S LANGUAGE asking the user to ask something more specific and "
        "saying why. Empty when answerable is true.",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="When answerable is false, up to 3 concrete, specific example "
        "questions IN THE QUESTION'S LANGUAGE that the user might have meant "
        "(e.g. about the budget, the euro, judicial reform). Empty when "
        "answerable is true.",
    )

    @field_validator("message")
    @classmethod
    def _clean_message(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("suggestions")
    @classmethod
    def _clean_suggestions(cls, v: list[str]) -> list[str]:
        """Coerce to a clean list of up to 3 non-empty strings."""
        return [s.strip() for s in v if s and s.strip()][:3]


def assess(question: str) -> QueryAssessment:
    """Classify whether ``question`` is specific enough for the retrieval pipeline.

    Returns a :class:`QueryAssessment`. **Never raises** — every failure path
    (missing key, provider error, malformed tool call) returns an *answerable*
    verdict so the gate degrades to a no-op rather than blocking a legitimate
    question.

    ``method="function_calling"`` because Anthropic models via OpenRouter don't
    honor ``response_format``, but they do honor tool calls.
    """
    question = (question or "").strip()
    if not question:
        # Empty input isn't the gate's problem; let the normal path handle it.
        return QueryAssessment(answerable=True, reason="empty question")

    try:
        judge = llm.router_model().with_structured_output(
            QueryAssessment, method="function_calling"
        )
        verdict = judge.invoke([
            ("system", prompts.ROUTER_SYSTEM_PROMPT),
            ("user", question),
        ])
        if not verdict.answerable:
            return verdict
        return QueryAssessment(answerable=True, reason=verdict.reason)
    except (Exception, SystemExit) as e:  # noqa: BLE001 — fail OPEN: a broken gate must not block
        return QueryAssessment(answerable=True, reason=f"router error: {e}")
