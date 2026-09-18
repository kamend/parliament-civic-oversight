# Civic Oversight

A retrieval-augmented question-answering app over Bulgarian Parliament plenary
transcripts. Ask what was said in the plenary hall and get a short, grounded
answer that cites the exact speaker turns it came from (`[S#]`) — every claim
links back to the original record.

Retrieval runs locally over a [LanceDB](https://lancedb.com/) index (dense
`BAAI/bge-m3` vectors + BM25, fused and cross-encoder reranked). Generation uses
any OpenAI-compatible LLM. The backend is Python / FastAPI (SSE streaming); the
frontend is Next.js.

It has three parts:

- **Ingestion** — downloads transcripts from parliament.bg and builds the search index.
- **Backend** — a FastAPI service that serves the API over that index.
- **Frontend** — a Next.js chat UI.

Ingestion and the backend share one Python environment under `backend/`.

## Prerequisites

- **Python ≥ 3.10** with [`uv`](https://docs.astral.sh/uv/) — for ingestion and the backend.
- **Node.js** with [`pnpm`](https://pnpm.io/) — for the frontend.
- An **API key for an OpenAI-compatible LLM** — needed for answer generation only;
  retrieval and embeddings run locally with no key.

## 1. Ingestion — build the index

```bash
cd backend
uv sync                       # install deps into .venv
cp .env.example .env          # set OPENROUTER_API_KEY (see "LLM provider" below)

# Download and index a month of sittings (pick any date selector):
uv run python -m parl_rag.cli ingest --year 2026 --month 6
```

The first run downloads the embedding model (`bge-m3`, ~2.3 GB) from Hugging Face
and caches it. Re-running is safe — each sitting is upserted by id, so dates are
replaced rather than duplicated. Other selectors: `--date 2026-06-11` (one day),
`--since 2026-04 --until 2026-06` (a range). Full reference in
[`backend/INGESTION.md`](backend/INGESTION.md).

## 2. Backend — the API

From `backend/` (same environment as ingestion):

```bash
uv run uvicorn parl_rag.api.main:app --host 127.0.0.1 --port 8077
```

Serves the API at `http://127.0.0.1:8077` (Swagger UI at `/docs`). More in
[`backend/API.md`](backend/API.md).

## 3. Frontend — the UI

```bash
cd frontend
pnpm install
pnpm dev                      # http://localhost:3000
```

## Run with Docker

A `docker-compose.yml` runs both services together. The backend reads the
LanceDB index from `./data` (bind-mounted) and caches model weights on a named
volume; the frontend proxies `/api/*` to the backend over the compose network.

```bash
cp backend/.env.example backend/.env   # set OPENROUTER_API_KEY
# Build the index first (host or container) — see backend/INGESTION.md.
docker compose up --build
```

The UI is at `http://localhost:3000`, the API at `http://localhost:8077`.

Notes:

- **Models** (`bge-m3` + reranker, ~5 GB) download on first boot into the
  `hf_cache` volume, so the backend's healthcheck has a long `start_period`.
  Subsequent starts are fast.
- **Data** lives in `./data` on the host, bind-mounted into the backend, so the
  index you build persists and is picked up by the API automatically.

### Ingestion in Docker

The ingest CLI runs inside the backend container — no paths or keys to pass, as
the `./data` mount, the `hf_cache` model volume, and `backend/.env` are all
already wired up by `docker-compose.yml`. Pick the form that matches your state:

```bash
# Stack already running (docker compose up) — run inside the live container:
docker compose exec backend python -m parl_rag.cli ingest --year 2026 --month 6

# Stack down — run a one-off container that cleans itself up:
docker compose run --rm backend python -m parl_rag.cli ingest --year 2026 --month 6
```

Other selectors work the same: `--date 2026-06-11` (one day),
`--since 2026-04 --until 2026-06` (a range), `--skip-existing` to skip days
already on disk. The first run is slow (downloads the embedder, embeds every
chunk, and makes LLM calls for the contextual step); later runs reuse the cached
model and only re-embed changed sittings. Full reference in
[`backend/INGESTION.md`](backend/INGESTION.md).

## LLM provider — any OpenAI-compatible API

Answer generation uses the `openai` SDK against any OpenAI-compatible endpoint,
so switching providers is just configuration — no code changes. It works with
OpenRouter (the default), OpenAI, Groq, DeepSeek, a local Ollama / LM Studio
server, or anything else that speaks the OpenAI API.

Set three variables in `backend/.env`:

| Variable | What it is |
|---|---|
| `OPENROUTER_API_KEY` | API key for your provider. The variables are named after OpenRouter, the default, but they apply to whichever endpoint you set. Required for OpenRouter; a keyless local server can leave it empty. |
| `OPENROUTER_BASE_URL` | The OpenAI-compatible base URL. Defaults to OpenRouter; e.g. `https://api.openai.com/v1`, or `http://localhost:11434/v1` for Ollama. |
| `PARL_LLM_MODEL` | The model slug to use, as named by that provider (e.g. `openai/gpt-5`, `gpt-4o`, `deepseek/deepseek-chat`). |

See [`backend/.env.example`](backend/.env.example) for all options, including the
cheaper models used for the ingestion-time context step and the answerability gate.

## License

Released under the [MIT License](LICENSE).
