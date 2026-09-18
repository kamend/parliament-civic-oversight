# Ingestion — keeping the index up to date

How to download Bulgarian Parliament plenary transcripts and (re)index them into
LanceDB. Run these from `backend/` with [`uv`](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync   # once, installs deps into .venv
```

The first indexing run loads **bge-m3** (~2.3 GB) to embed chunks. Weights are
downloaded once from Hugging Face and cached under `~/.cache/huggingface/`;
later runs reuse them.

---

## TL;DR — the update you'll run most often

New sittings happen a few times a week. To pull the current month and fold any
new days into the index:

```bash
uv run python -m parl_rag.cli ingest --year 2026 --month 6
```

This is **safe to re-run**: each sitting is upserted by `transcript_id`
(delete-then-add), so re-ingesting a date *replaces* its rows instead of
duplicating them. Already-published days are re-fetched and re-embedded; days
that are still placeholders are skipped until their transcript is published.

To avoid re-downloading days you already have on disk, add `--skip-existing`:

```bash
uv run python -m parl_rag.cli ingest --year 2026 --month 6 --skip-existing
```

---

## Picking what to ingest

Pick exactly one date selector:

| Goal | Command |
|---|---|
| One sitting by date | `--date 2026-06-11` |
| A whole month | `--year 2026 --month 6` |
| A month range (inclusive) | `--since 2026-05 --until 2026-06` |

```bash
# a single day
uv run python -m parl_rag.cli ingest --date 2026-06-11

# backfill a span of months
uv run python -m parl_rag.cli ingest --since 2026-04 --until 2026-06
```

Each sitting is saved as three files under
`data/transcripts/<YYYY-MM>/<date>_<id>.{json,html,txt}` (raw response, HTML
body, plain text). The `.txt` is what the parser reads.

---

## Common flags

| Flag | What it does |
|---|---|
| `--skip-existing` | Don't refetch a sitting whose `.txt` is already downloaded (placeholders are still refetched). |
| `--offline` | Index transcripts already on disk; make **no** network calls. |
| `--reset` | Drop the table first — a full rebuild from scratch. |
| `--no-index` | Load rows but skip building the FTS/scalar indexes (build them later). |
| `--delay 0.5` | Seconds to wait between downloads (be polite to parliament.bg). |
| `--data-dir`, `--db-path`, `--table` | Override the transcript dir / LanceDB path / table name. |

See everything with `uv run python -m parl_rag.cli ingest --help`.

---

## Recipes

**Full rebuild from transcripts already on disk** (no network, drops + recreates
the table):

```bash
uv run python -m parl_rag.cli ingest --since 2026-04 --until 2026-06 --offline --reset
```

**Re-index just one day** (e.g. its transcript got published or corrected):

```bash
uv run python -m parl_rag.cli ingest --date 2026-06-11
```

**Fresh download of a month without touching files you already have:**

```bash
uv run python -m parl_rag.cli ingest --year 2026 --month 6 --skip-existing
```

---

## What a run reports

The CLI prints per-sitting progress and a final summary, e.g.:

```
  ✓ 2026-06-05 id=11135: 243 turns → 384 chunks
Building FTS + scalar indexes ...
Table now holds 4349 rows.

Summary: 17 sitting(s) seen · 0 downloaded · 17 reused · 2 placeholder(s) · 15 indexed (4349 chunks) · 0 empty
```

- **placeholder** — the sitting has no published transcript yet (a short stub);
  it is skipped. Re-run later to pick it up.
- **empty** — parsed but produced no speaker turns; skipped.
- **reused** — already on disk, not re-downloaded (`--skip-existing` / `--offline`).

---

## Verify the index

```bash
uv run python -c "
from parl_rag.store import LanceDBStore
s = LanceDBStore()
print('rows:', s.count())
print(s.metadata_summary())   # parties, speakers, date range — feeds /api/filters
"
```

A quick search smoke-test — use the `query` command:

```bash
uv run python -m parl_rag.cli query "бюджет" -k 3
uv run python -m parl_rag.cli query "пенсии" --party ВЪЗРАЖДАНЕ --no-rerank
uv run python -m parl_rag.cli query "еврото" --since 2026-06-01 --full
```

It runs the same hybrid → filter → rerank path the API uses and prints the hits
(score, speaker/party, and a snippet). See `--help` for all filters.

---

## Where things live

| Path | What |
|---|---|
| `data/transcripts/<YYYY-MM>/` | Raw downloads (`.json` / `.html` / `.txt`). |
| `data/lancedb/` | The LanceDB store (table `turns` by default). |

Both default under `production/data/` and can be relocated with `--data-dir` /
`--db-path` or the `PARL_DATA_DIR` / `LANCEDB_PATH` environment variables (see
`.env.example`).
