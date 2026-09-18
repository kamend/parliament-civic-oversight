from __future__ import annotations

import functools

from langchain_openai import ChatOpenAI

from . import config


def _is_openrouter() -> bool:
    return "openrouter.ai" in config.OPENROUTER_BASE_URL


def _chat_model(model: str, **kwargs) -> ChatOpenAI:
    """Build a ChatOpenAI for the configured endpoint.

    OpenRouter is the default, but ``OPENROUTER_BASE_URL`` can point at any
    OpenAI-compatible server. The key is only enforced for OpenRouter itself: a
    local server (Ollama, LM Studio) needs none, and any other provider reports
    a bad key in its own words.
    """
    if _is_openrouter() and not config.OPENROUTER_API_KEY:
        raise SystemExit(
            "No OPENROUTER_API_KEY found. Either create backend/.env with:\n"
            "    OPENROUTER_API_KEY=sk-or-...\n"
            "(copy .env.example to .env), or export OPENROUTER_API_KEY in your shell.\n"
            "Get a key at https://openrouter.ai/keys."
        )
    # Optional attribution on OpenRouter's dashboards / leaderboards. Other
    # endpoints have no use for these headers, so they aren't sent there.
    headers = {
        "HTTP-Referer": config.OPENROUTER_SITE_URL,
        "X-Title": config.OPENROUTER_APP_TITLE,
    } if _is_openrouter() else None
    return ChatOpenAI(
        model=model,
        base_url=config.OPENROUTER_BASE_URL,
        # The client rejects an empty key, so keyless servers get a placeholder.
        api_key=config.OPENROUTER_API_KEY or "not-needed",
        default_headers=headers,
        **kwargs,
    )


@functools.lru_cache(maxsize=1)
def answer_model() -> ChatOpenAI:
    """The generator. ``stream_usage=True`` asks OpenRouter to append a final
    usage-only chunk, which LangChain surfaces as ``usage_metadata``."""
    return _chat_model(config.LLM_MODEL, max_tokens=4096, stream_usage=True)


@functools.lru_cache(maxsize=1)
def router_model() -> ChatOpenAI:
    """The answerability gate's model: cheap, and temperature 0 for stable
    verdicts."""
    return _chat_model(config.LLM_ROUTER_MODEL, max_tokens=400, temperature=0)
