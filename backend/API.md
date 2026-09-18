# Backend API — running and testing the service

The FastAPI service over the LanceDB index: health, filter values, and a
streaming, grounded, `[S#]`-cited answer endpoint. Run everything from `backend/`
with [`uv`](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync   # once, installs deps into .venv
```

> The index must already be built (`data/lancedb/`). If it isn't, ingest first —
> see [`INGESTION.md`](./INGESTION.md).

---

## Configure credentials

Retrieval (`/api/health`, `/api/filters`, and the `sources` of `/api/ask`) needs
**no** key. Generating an answer needs an OpenRouter key. Copy the example and
fill it in:

```bash
cp .env.example .env
# then edit .env and set:
#   OPENROUTER_API_KEY=sk-or-...
# optionally pick a model (any slug from https://openrouter.ai/models):
#   PARL_LLM_MODEL=anthropic/claude-opus-4.8
```

The generator routes through OpenRouter's OpenAI-compatible API, so switching
models is just changing `PARL_LLM_MODEL` — no code or restart-of-models needed.

Without a key the `/api/ask` stream still returns its `sources`, then emits an
`error` event on the generation stage instead of the answer — handy for testing
retrieval in isolation.

---

## Start the server

```bash
uv run uvicorn parl_rag.api.main:app --host 127.0.0.1 --port 8077
```

On startup the app **warms the models once** — bge-m3 (embedder) and
bge-reranker-v2-m3 (cross-encoder), ~4.6 GB total — so the first request isn't
slow. Watch for `Application startup complete`, then `models_warm` flips true in
`/api/health`. Bound to `127.0.0.1`, so it's local-only.

Useful flags:

| Flag | What it does |
|---|---|
| `--reload` | Auto-restart on code changes (dev). Note: reload re-warms the models on every restart. |
| `--port 8077` | Change the port (examples below use 8077). |
| `--workers N` | N independent processes for concurrency — **each loads its own ~4.6 GB of models**, so mind the RAM. See the note at the bottom. |

Interactive docs (Swagger UI) once it's up: <http://127.0.0.1:8077/docs>.

---

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Readiness: table reachable, row count, are the models warm. |
| `GET /api/filters` | Distinct parties, speakers, and the date range — populates the UI filter bar. |
| `POST /api/ask` | Hybrid retrieve → rerank → **stream** a grounded, cited answer over SSE. |

`POST /api/ask` body (only `question` is required):

```jsonc
{
  "question": "Какво беше казано за бюджета?",
  "party":   "ГЕРБ-СДС",   // optional, exact match
  "speaker": "Владислав Горанов", // optional, exact display name
  "since":   "2026-05-01",  // optional, YYYY-MM-DD (inclusive)
  "until":   "2026-06-05",  // optional, YYYY-MM-DD (inclusive)
  "date":    "2026-05-20",  // optional, single day
  "k":       3,              // sources to ground on (1–20, default 5)
  "rerank":  true            // cross-encoder rerank (default true; false is faster)
}
```

The response is an **SSE stream** with three event types, in order:

1. `sources` — the reranked turns: `{"sources": [{ "n": 1, "speaker": …, "party": …, "date": …, "text": …, "score": … }, …]}`. The `n` matches the `[S#]` tags in the answer.
2. `token`* — answer fragments as Claude writes them: `{"text": "…"}`.
3. `done` — the full answer plus usage: `{"answer": …, "model": …, "input_tokens": …, "output_tokens": …}`.

On failure (or no results) you get `error` / a `done` with `"no_results": true`
instead of the token run.