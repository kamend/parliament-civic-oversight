from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# parl_rag/settings.py -> parl_rag -> backend -> production (project root)
PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

# Load .env into os.environ, not just into Settings: LangSmith reads its
# LANGSMITH_* variables straight from the environment, so they have to land
# there for tracing to work. Backend dir first, then the project root, so a key
# placed at either level is found. A variable already set in the real
# environment is never overridden, so an explicit `export` still wins.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Everything configurable from the environment. The defaults run the stack
    from a source checkout with no .env beyond the API key."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    # ----------------------------------------------------------------------- #
    # Paths
    # ----------------------------------------------------------------------- #
    # Raw transcripts (json/html/txt, by month) and the embedded LanceDB store
    # both live under production/data/. Override either via the environment so
    # the same code runs in Docker with volume mounts.
    data_dir: Path = Field(PROJECT_ROOT / "data" / "transcripts", validation_alias="PARL_DATA_DIR")
    lancedb_path: Path = Field(PROJECT_ROOT / "data" / "lancedb", validation_alias="LANCEDB_PATH")
    # The Lance table that holds one row per chunk (see retrieval/store.py).
    lancedb_table: str = Field("turns", validation_alias="LANCEDB_TABLE")

    # ----------------------------------------------------------------------- #
    # Chunking
    # ----------------------------------------------------------------------- #
    # Turns shorter than this many words are not indexed. They are almost always
    # the chair running procedure ("Заповядайте.", "Благодаря Ви, господин
    # Иванов.") — noise that embeds degenerately and that BM25 actively
    # over-scores because it favors very short documents. Substantive short
    # remarks (реплики) run longer. Set 0 to index every turn. Changing this only
    # affects future ingests; pass --force to re-ingest transcripts already in
    # the store.
    min_turn_words: int = Field(10, validation_alias="PARL_MIN_TURN_WORDS")

    # ----------------------------------------------------------------------- #
    # Models
    # ----------------------------------------------------------------------- #
    # Embedding model. The corpus is Bulgarian (Cyrillic), so a MULTILINGUAL
    # model is non-negotiable — an English-only embedder would be near-useless.
    #
    #   BAAI/bge-m3            -> strong multilingual, 1024-dim, 8k context. Default.
    #   intfloat/multilingual-e5-base -> lighter (768-dim), needs "query:"/"passage:"
    #                            prefixes. Good fallback on a small machine.
    embed_model: str = Field("BAAI/bge-m3", validation_alias="PARL_EMBED_MODEL")

    # Cross-encoder reranker. v2-m3 is multilingual and pairs with bge-m3.
    rerank_model: str = Field("BAAI/bge-reranker-v2-m3", validation_alias="PARL_RERANK_MODEL")

    # Generator. Routed through OpenRouter's OpenAI-compatible API, so the model
    # is just a swappable slug — anything from https://openrouter.ai/models
    # works, e.g. "anthropic/claude-opus-4.8", "openai/gpt-5",
    # "google/gemini-2.5-pro", "deepseek/deepseek-chat". (Verify the exact slug
    # on openrouter.ai/models — they don't carry date suffixes.)
    llm_model: str = Field("anthropic/claude-opus-4.8", validation_alias="PARL_LLM_MODEL")

    # The answerability gate (answering/gate.py) runs once before every
    # retrieval, so it wants to be cheap and fast — default to a light model.
    llm_router_model: str = Field(
        "anthropic/claude-haiku-4.5", validation_alias="PARL_LLM_ROUTER_MODEL"
    )

    # ----------------------------------------------------------------------- #
    # OpenRouter (OpenAI-compatible LLM gateway)
    # ----------------------------------------------------------------------- #
    # One key, every provider. Create one at https://openrouter.ai/keys. The base
    # URL is overridable so you can point at a self-hosted/OpenAI-compatible
    # gateway instead. SITE_URL / APP_TITLE are optional attribution shown on
    # OpenRouter's dashboards and model leaderboards (sent as HTTP-Referer /
    # X-Title headers).
    openrouter_api_key: SecretStr = Field(SecretStr(""), validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        "https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )
    openrouter_site_url: str = Field("http://localhost:3000", validation_alias="OPENROUTER_SITE_URL")
    openrouter_app_title: str = Field("Parliament RAG", validation_alias="OPENROUTER_APP_TITLE")

    # ----------------------------------------------------------------------- #
    # Service
    # ----------------------------------------------------------------------- #
    # Origin the Next.js frontend is served from; the FastAPI app opens CORS to
    # it. Comma-separated list supported.
    cors_origin: str = Field("http://localhost:3000", validation_alias="CORS_ORIGIN")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]


settings = Settings()
