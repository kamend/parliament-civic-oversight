#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

# Make the backend package importable when run as a file (python scripts/query.py):
# the script's own dir is on sys.path[0], not the backend root, so add it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="query.py",
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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from parl_rag.store import LanceDBStore

    store = LanceDBStore(path=args.db_path, table_name=args.table)
    if not store.exists():
        print(f"No table '{store.table_name}' at {store.path}.\n"
              f"Ingest some transcripts first:  uv run python -m parl_rag.ingest --help",
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


if __name__ == "__main__":
    sys.exit(main())
