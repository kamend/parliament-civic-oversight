from __future__ import annotations

import functools

from langchain_openai import ChatOpenAI

from ..settings import settings


def _is_openrouter() -> bool:
    return "openrouter.ai" in settings.openrouter_base_url


def _chat_model(model: str, **kwargs) -> ChatOpenAI:
    """Build a ChatOpenAI for the configured endpoint.

    OpenRouter is the default, but ``OPENROUTER_BASE_URL`` can point at any
    OpenAI-compatible server. The key is only enforced for OpenRouter itself: a
    local server (Ollama, LM Studio) needs none, and any other provider reports
    a bad key in its own words.
    """
    api_key = settings.openrouter_api_key.get_secret_value()
    if _is_openrouter() and not api_key:
        raise SystemExit(
            "No OPENROUTER_API_KEY found. Either create backend/.env with:\n"
            "    OPENROUTER_API_KEY=sk-or-...\n"
            "(copy .env.example to .env), or export OPENROUTER_API_KEY in your shell.\n"
            "Get a key at https://openrouter.ai/keys."
        )
    # Optional attribution on OpenRouter's dashboards / leaderboards. Other
    # endpoints have no use for these headers, so they aren't sent there.
    headers = {
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_app_title,
    } if _is_openrouter() else None
    return ChatOpenAI(
        model=model,
        base_url=settings.openrouter_base_url,
        # The client rejects an empty key, so keyless servers get a placeholder.
        api_key=api_key or "not-needed",
        default_headers=headers,
        **kwargs,
    )


@functools.lru_cache(maxsize=1)
def answer_model() -> ChatOpenAI:
    """The generator. ``stream_usage=True`` asks OpenRouter to append a final
    usage-only chunk, which LangChain surfaces as ``usage_metadata``."""
    return _chat_model(settings.llm_model, max_tokens=4096, stream_usage=True)


@functools.lru_cache(maxsize=1)
def gate_model() -> ChatOpenAI:
    """The answerability gate's model: cheap, and temperature 0 for stable
    verdicts."""
    return _chat_model(settings.llm_router_model, max_tokens=400, temperature=0)
