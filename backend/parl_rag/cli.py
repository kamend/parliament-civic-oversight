"""Command line for the backend's two tools.

    uv run python -m parl_rag.cli ingest --year 2026 --month 6
    uv run python -m parl_rag.cli query "бюджет" -k 3

Argument parsing and printing live here; the work is in ``parl_rag.ingest`` and
``parl_rag.retrieval.store``.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from .settings import settings

Month = tuple[int, int]


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #
def _parse_month(token: str) -> Month:
    """'2026-06' or '2026-6' → (2026, 6)."""
    try:
        y, m = token.split("-")
        year, month = int(y), int(m)
    except ValueError:
        raise SystemExit(f"--since/--until want YYYY-MM, got {token!r}")
    if not 1 <= month <= 12:
        raise SystemExit(f"month out of range in {token!r}")
    return year, month


def _parse_date(token: str) -> tuple[int, int, int]:
    """'2026-06-11' → (2026, 6, 11)."""
    try:
        y, m, d = token.split("-")
        return int(y), int(m), int(d)
    except ValueError:
        raise SystemExit(f"--date wants YYYY-MM-DD, got {token!r}")


def _resolve_months(args) -> list[Month]:
    """Turn the CLI date selectors into the list of (year, month) to scan."""
    from .corpus.download import iter_months

    if args.date:
        y, m, _ = _parse_date(args.date)
        return [(y, m)]
    if args.since or args.until:
        if not (args.since and args.until):
            raise SystemExit("--since and --until must be given together")
        return list(iter_months(_parse_month(args.since), _parse_month(args.until)))
    if args.year and args.month:
        if not 1 <= args.month <= 12:
            raise SystemExit("--month must be 1-12")
        return [(args.year, args.month)]
    raise SystemExit(
        "pick a date selector: --date YYYY-MM-DD | --since YYYY-MM --until YYYY-MM "
        "| --year YYYY --month M"
    )


def _add_ingest_parser(sub) -> None:
    p = sub.add_parser(
        "ingest",
        help="download transcripts and index them",
        description="Download parliament.bg transcripts and index them into LanceDB.",
    )
    sel = p.add_argument_group("date selectors (pick one)")
    sel.add_argument("--date", help="single sitting, YYYY-MM-DD")
    sel.add_argument("--since", help="start month (inclusive), YYYY-MM")
    sel.add_argument("--until", help="end month (inclusive), YYYY-MM")
    sel.add_argument("--year", type=int, help="with --month: a whole month")
    sel.add_argument("--month", type=int, help="with --year: a whole month (1-12)")

    opt = p.add_argument_group("options")
    opt.add_argument("--offline", action="store_true",
                     help="index transcripts already on disk; no network calls")
    opt.add_argument("--skip-existing", action="store_true",
                     help="don't refetch a sitting whose .txt is already downloaded")
    opt.add_argument("--reset", action="store_true",
                     help="drop the table before indexing (full rebuild)")
    opt.add_argument("--force", action="store_true",
                     help="re-ingest sittings already in the store (default: skip them)")
    opt.add_argument("--no-index", action="store_true",
                     help="load rows but skip building FTS/scalar indexes")
    opt.add_argument("--delay", type=float, default=0.5,
                     help="seconds between transcript downloads (default 0.5)")
    opt.add_argument("--data-dir", type=Path, default=settings.data_dir,
                     help=f"raw transcripts root (default {settings.data_dir})")
    opt.add_argument("--db-path", type=Path, default=settings.lancedb_path,
                     help=f"LanceDB directory (default {settings.lancedb_path})")
    opt.add_argument("--table", default=settings.lancedb_table,
                     help=f"LanceDB table name (default {settings.lancedb_table})")
    p.set_defaults(func=_ingest)


def _ingest(args) -> int:
    from . import ingest

    months = _resolve_months(args)
    span = f"{months[0][0]}-{months[0][1]:02d}"
    if len(months) > 1:
        span += f" … {months[-1][0]}-{months[-1][1]:02d}"
    if args.date:
        span = args.date
    print(f"Ingesting {span}  ({'offline' if args.offline else 'download'} mode)\n")

    summary = ingest.run(
        months, date=args.date, offline=args.offline, skip_existing=args.skip_existing,
        reset=args.reset, force=args.force, build_indexes=not args.no_index,
        delay=args.delay, data_dir=args.data_dir, db_path=args.db_path, table=args.table,
    )
    if summary.sittings:
        print(
            "\nSummary: "
            f"{summary.sittings} sitting(s) seen · {summary.downloaded} downloaded · "
            f"{summary.reused} reused · {summary.placeholders} placeholder(s) · "
            f"{summary.already} already indexed · "
            f"{summary.indexed} indexed ({summary.chunks} chunks) · {summary.empty} empty"
        )
    return 0


# --------------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------------- #
def _add_query_parser(sub) -> None:
    p = sub.add_parser(
        "query",
        help="hybrid search the store and print results",
        description="Hybrid search the parliament LanceDB store and print results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("question", help="the search query (Cyrillic is fine)")
    p.add_argument("-k", type=int, default=5, help="number of results (default 5)")

    flt = p.add_argument_group("filters (optional, AND-ed, exact match)")
    flt.add_argument("--party", help="e.g. ВЪЗРАЖДАНЕ, ГЕРБ-СДС")
    flt.add_argument("--speaker", help="display name, e.g. 'Бойко Борисов'")
    flt.add_argument("--date", help="single day, YYYY-MM-DD")
    flt.add_argument("--since", help="from this date (inclusive), YYYY-MM-DD")
    flt.add_argument("--until", help="up to this date (inclusive), YYYY-MM-DD")

    out = p.add_argument_group("output")
    out.add_argument("--no-rerank", dest="rerank", action="store_false",
                     help="skip the cross-encoder rerank (faster; hybrid order)")
    out.add_argument("--full", action="store_true",
                     help="print each hit's full text instead of a snippet")
    out.add_argument("--db-path", help="override LanceDB directory")
    out.add_argument("--table", help="override table name")
    p.set_defaults(func=_query)


def _query(args) -> int:
    from .retrieval.store import LanceDBStore

    store = LanceDBStore(path=args.db_path, table_name=args.table)
    if not store.exists():
        print(f"No table '{store.table_name}' at {store.path}.\n"
              f"Ingest some transcripts first:  uv run python -m parl_rag.cli ingest --help",
              file=sys.stderr)
        return 1

    filters = {k: v for k, v in (
        ("party", args.party), ("speaker", args.speaker), ("date", args.date),
        ("since", args.since), ("until", args.until),
    ) if v}

    print(f'Query: {args.question!r}  (k={args.k}, rerank={args.rerank}'
          + (f', {filters}' if filters else "") + ")")
    print(f"Store: {store.path}/{store.table_name}  ({store.count()} rows)\n")

    hits = store.search(args.question, k=args.k, rerank=args.rerank, **filters)
    if not hits:
        print("No results." + (" Try loosening the filters." if filters else ""))
        return 0

    for i, h in enumerate(hits, 1):
        c = h.chunk
        who = c.speaker or "?"
        bits = [b for b in (c.metadata.get("role"), c.party) if b]
        who += f" ({', '.join(bits)})" if bits else ""
        rank_note = ""
        if h.reranked and h.prior_rank is not None:
            rank_note = f"  [hybrid #{h.prior_rank} → rerank #{i}]"

        print(f"[{i}] score={h.score:.4f}  hybrid={h.hybrid_score:.4f}{rank_note}")
        print(f"    {c.date}  {who}")
        print(f"    transcript {c.metadata.get('transcript_id')}  turn {c.metadata.get('turn_index')}")
        body = c.text.strip()
        if args.full:
            print(textwrap.indent(body, "    "))
        else:
            snippet = " ".join(body.split())
            print("    " + textwrap.shorten(snippet, width=240, placeholder=" …"))
        print()

    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="parl_rag.cli", description="Parliament RAG backend tools.")
    sub = p.add_subparsers(dest="command", required=True)
    _add_ingest_parser(sub)
    _add_query_parser(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
