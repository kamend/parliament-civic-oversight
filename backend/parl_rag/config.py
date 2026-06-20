from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# parl_rag/config.py -> parl_rag -> backend -> production (project root)
PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

# Raw transcripts (json/html/txt, by month) and the embedded LanceDB store both
# live under production/data/. Override either via the environment so the same
# code runs in Docker with volume mounts.
DATA_DIR = Path(os.environ.get("PARL_DATA_DIR", PROJECT_ROOT / "data" / "transcripts"))
LANCEDB_PATH = Path(os.environ.get("LANCEDB_PATH", PROJECT_ROOT / "data" / "lancedb"))

# The Lance table that holds one row per chunk (see store.py, phase 2).
LANCEDB_TABLE = os.environ.get("LANCEDB_TABLE", "turns")

# --------------------------------------------------------------------------- #
# .env loading
# --------------------------------------------------------------------------- #
# The service needs an OpenRouter key for generation. Rather than make every
# caller `export OPENROUTER_API_KEY=...`, we load a .env file here, at import
# time, so the key (and any PARL_* / LANCEDB_* overrides) are available
# everywhere. Dependency-free on purpose.


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a simple KEY=VALUE .env file.

    Mirrors python-dotenv's default behavior: comments (#), blank lines, and an
    optional `export ` prefix are handled, surrounding quotes are stripped, and a
    variable that is ALREADY set in the real environment is NOT overridden — so an
    explicit `export OPENROUTER_API_KEY=...` still wins over the .env file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)   # setdefault = don't override real env


# Look in the backend dir first, then the project root, so a key placed at
# either level is found. Loaded before the Models section below so PARL_*
# overrides take effect.
_load_dotenv(BACKEND_DIR / ".env")
_load_dotenv(PROJECT_ROOT / ".env")

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
# Embedding model. The corpus is Bulgarian (Cyrillic), so a MULTILINGUAL model
# is non-negotiable — an English-only embedder would be near-useless here.
#
#   BAAI/bge-m3            -> strong multilingual, 1024-dim, 8k context. Default.
#   intfloat/multilingual-e5-base -> lighter (768-dim), needs "query:"/"passage:"
#                            prefixes. Good fallback on a small machine.
#
# Override from the shell:  export PARL_EMBED_MODEL=intfloat/multilingual-e5-base
EMBED_MODEL = os.environ.get("PARL_EMBED_MODEL", "BAAI/bge-m3")

# Cross-encoder reranker. v2-m3 is multilingual and pairs with bge-m3.
RERANK_MODEL = os.environ.get("PARL_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

# Generator. Routed through OpenRouter's OpenAI-compatible API, so the model is
# just a swappable slug — anything from https://openrouter.ai/models works, e.g.
# "anthropic/claude-opus-4.8", "openai/gpt-5", "google/gemini-2.5-pro",
# "deepseek/deepseek-chat". Switching models is a pure config change, no code.
# (Verify the exact slug on openrouter.ai/models — they don't carry date suffixes.)
LLM_MODEL = os.environ.get("PARL_LLM_MODEL", "anthropic/claude-opus-4.8")

# A cheaper/faster model for the high-volume, ingestion-time context step.
LLM_CONTEXT_MODEL = os.environ.get("PARL_LLM_CONTEXT_MODEL", "anthropic/claude-haiku-4.5")

# The query-routing gate (parl_rag.router) runs once before every retrieval, so
# it wants to be cheap and fast — default to the same light model as the context
# step. Override independently if you want a stronger judge for the gate.
LLM_ROUTER_MODEL = os.environ.get("PARL_LLM_ROUTER_MODEL", LLM_CONTEXT_MODEL)

# --------------------------------------------------------------------------- #
# OpenRouter (OpenAI-compatible LLM gateway)
# --------------------------------------------------------------------------- #
# One key, every provider. Create one at https://openrouter.ai/keys. The base
# URL is overridable so you can point at a self-hosted/OpenAI-compatible gateway
# instead. SITE_URL / APP_TITLE are optional attribution shown on OpenRouter's
# dashboards and model leaderboards (sent as HTTP-Referer / X-Title headers).
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "http://localhost:3000")
OPENROUTER_APP_TITLE = os.environ.get("OPENROUTER_APP_TITLE", "Parliament RAG")

# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
# Origin the Next.js frontend is served from; the FastAPI app (phase 4) opens
# CORS to it. Comma-separated list supported.
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "http://localhost:3000")

# --------------------------------------------------------------------------- #
# Bulgarian parliamentary groups.
# Party tags appear in parentheses after a speaker's name, e.g. "ЙОРДАН ИВАНОВ (ДБ):".
# PARTIES maps each canonical abbreviation → its full display name.
# --------------------------------------------------------------------------- #
PARTIES = {
    "ПП": "Продължаваме промяната",
    "ДБ": "Демократична България",
    "ПП-ДБ": "Продължаваме промяната – Демократична България",
    "ПБ": "Прогресивна България",
    "ГЕРБ-СДС": "ГЕРБ-СДС",
    "ВЪЗРАЖДАНЕ": "Възраждане",
    "ДПС": "Движение за права и свободи",
    "БСП": "БСП за България",
    "ИТН": "Има такъв народ",
    "МЕЧ": "Морал, Единство, Чест",
    "НН": "Ново начало",
}

# The same group is written inconsistently across transcripts — sometimes the
# abbreviation "(ПП)", sometimes the full name "(Продължаваме Промяната)", with
# varied casing and dash characters. PARTY_ALIASES maps a canonical abbreviation
# → the alternate spellings seen in the wild, so ingestion can fold every variant
# onto one key (see normalize_party). Add a new spelling here, not in code.
# Matching is case-insensitive and dash-insensitive ("–"/"—"/"-" are equivalent),
# so only genuinely distinct wordings need listing.
PARTY_ALIASES = {
    "ПП": ["Продължаваме промяната"],
    "ПБ": ["Прогресивна България"],
    "ДБ": ["Демократична България"],
    "ДПС": [
        "Движение за права и свободи",
        "Движение за права и свободи - ДПС",
        "ДПС - Ново начало",
    ],
    "ПП-ДБ": ["Продължаваме промяната - Демократична България"],
}


def _party_key(label: str) -> str:
    """Normalize a party label for matching: unify dash glyphs, collapse spaces
    around dashes and runs of whitespace, and casefold. So "Продължаваме
    Промяната – Демократична България" and "...промяната-Демократична България"
    map to the same key."""
    s = label.replace("–", "-").replace("—", "-")
    s = " ".join(s.split())            # collapse whitespace
    s = s.replace(" - ", "-")          # "ГЕРБ - СДС" → "ГЕРБ-СДС"
    return s.casefold()


# Precomputed { normalized spelling -> canonical abbreviation }. Includes every
# canonical key itself plus all its aliases.
_PARTY_CANON = {}
for _canon, _aliases in PARTY_ALIASES.items():
    for _label in (_canon, *_aliases):
        _PARTY_CANON[_party_key(_label)] = _canon
for _canon in PARTIES:
    _PARTY_CANON.setdefault(_party_key(_canon), _canon)


def normalize_party(party: str | None) -> str | None:
    """Fold a raw party tag onto its canonical abbreviation.

    Known spellings (any casing/dash variant) map to the canonical key from
    PARTIES/PARTY_ALIASES; an unrecognized tag is returned trimmed but otherwise
    untouched, so a new group still shows up (just not yet unified) rather than
    being dropped."""
    if not party:
        return None
    party = party.strip()
    return _PARTY_CANON.get(_party_key(party), party or None)

# Role prefixes that precede a name and are NOT part of it. Order matters:
# longer prefixes must be checked first ("ЗАМЕСТНИК-ПРЕДСЕДАТЕЛ" before "ПРЕДСЕДАТЕЛ").
ROLE_PREFIXES = [
    "ЗАМЕСТНИК-ПРЕДСЕДАТЕЛ",
    "ПРЕДСЕДАТЕЛ",
    "МИНИСТЪР-ПРЕДСЕДАТЕЛ",
    "ЗАМЕСТНИК МИНИСТЪР-ПРЕДСЕДАТЕЛ",
    "СЛУЖЕБЕН МИНИСТЪР-ПРЕДСЕДАТЕЛ",
    "МИНИСТЪР",
    "ГЛАВЕН СЕКРЕТАР",
    "ДОКЛАДЧИК",
]
