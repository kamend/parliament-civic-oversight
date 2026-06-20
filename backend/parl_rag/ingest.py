from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config
from .chunking import chunk_by_turn_windowed
from .download import (
    PLACEHOLDER_MAX_CHARS,
    ParliamentClient,
    Sitting,
    iter_months,
)
from .parsing import load_transcript


@dataclass
class Target:
    """One transcript to ingest, located on disk."""

    sitting: Sitting
    txt_path: Path
    placeholder: bool
    skipped_download: bool = False


@dataclass
class Summary:
    sittings: int = 0
    downloaded: int = 0
    reused: int = 0          # already on disk, not refetched
    placeholders: int = 0    # skipped: no published transcript yet
    already: int = 0         # skipped: transcript already in the store
    indexed: int = 0         # transcripts upserted
    chunks: int = 0
    empty: int = 0           # parsed but produced no turns/chunks


# --------------------------------------------------------------------------- #
# Date selection
# --------------------------------------------------------------------------- #
def _parse_month(token: str) -> tuple[int, int]:
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


def _resolve_months(args) -> list[tuple[int, int]]:
    """Turn the CLI date selectors into the list of (year, month) to scan."""
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


# --------------------------------------------------------------------------- #
# Locating transcripts (online: download; offline: scan disk)
# --------------------------------------------------------------------------- #
def _gather_online(args, months, client: ParliamentClient, summary: Summary) -> list[Target]:
    """List each month's sittings via the API and download them to disk."""
    date_filter = args.date  # only set for --date
    targets: list[Target] = []
    for year, month in months:
        sittings = client.list_sittings(year, month)
        if date_filter:
            sittings = [s for s in sittings if s.date == date_filter]
        if not sittings:
            print(f"  {year}-{month:02d}: no sittings found")
            continue
        print(f"  {year}-{month:02d}: {len(sittings)} sitting(s)")
        for s in sittings:
            summary.sittings += 1
            res = client.save_sitting(s, data_dir=args.data_dir, skip_existing=args.skip_existing)
            if res.skipped:
                summary.reused += 1
                tag = "reused"
            else:
                summary.downloaded += 1
                tag = f"{res.chars:>7} chars"
            if res.placeholder:
                summary.placeholders += 1
                tag += "  (placeholder — not yet published)"
            print(f"    {s.date} id={s.id}  {tag}")
            targets.append(Target(sitting=s, txt_path=res.txt_path, placeholder=res.placeholder,
                                  skipped_download=res.skipped))
    return targets


def _gather_offline(args, months, summary: Summary) -> list[Target]:
    """Find already-downloaded ``.txt`` files for the requested months on disk."""
    date_filter = args.date
    targets: list[Target] = []
    for year, month in months:
        month_dir = ParliamentClient.month_dir(args.data_dir, year, month)
        if not month_dir.is_dir():
            print(f"  {year}-{month:02d}: nothing on disk")
            continue
        paths = sorted(month_dir.glob("*.txt"))
        found = 0
        for p in paths:
            stem = p.stem                      # "2026-06-11_11137"
            date, _, tid = stem.partition("_")
            if date_filter and date != date_filter:
                continue
            chars = p.stat().st_size
            placeholder = chars < PLACEHOLDER_MAX_CHARS
            summary.sittings += 1
            summary.reused += 1
            if placeholder:
                summary.placeholders += 1
            targets.append(Target(
                sitting=Sitting(id=tid, date=date, year=year, month=month),
                txt_path=p, placeholder=placeholder, skipped_download=True,
            ))
            found += 1
        print(f"  {year}-{month:02d}: {found} transcript(s) on disk")
    return targets


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
def _ingest_targets(args, targets: list[Target], summary: Summary) -> None:
    """Parse → chunk → upsert every non-placeholder target into LanceDB."""
    from .store import LanceDBStore

    store = LanceDBStore(path=args.db_path, table_name=args.table)

    if args.reset and store.exists():
        print(f"\nReset: dropping table '{store.table_name}'")
        store.db.drop_table(store.table_name)

    to_index = [t for t in targets if not t.placeholder]

    # By default, skip sittings already in the store — re-embedding and
    # re-indexing transcripts that haven't changed is wasteful. --force re-ingests
    # them anyway (replacing their rows); --reset already cleared the table above.
    if not args.force:
        existing = store.existing_transcript_ids()
        fresh: list[Target] = []
        for t in to_index:
            if t.sitting.id in existing:
                summary.already += 1
                print(f"  = {t.sitting.date} id={t.sitting.id}: already indexed, skipped")
            else:
                fresh.append(t)
        to_index = fresh

    if not to_index:
        print("\nNothing new to index (all already indexed, placeholders, or empty).")
        print("  (pass --force to re-ingest transcripts already in the store)")
        return

    print(f"\nIndexing {len(to_index)} transcript(s) → {store.path}/{store.table_name}")
    print("(first run loads bge-m3 — ~2.3GB, downloads weights once)\n")

    for t in to_index:
        if not t.txt_path.exists():
            print(f"  ! {t.sitting.date} id={t.sitting.id}: {t.txt_path.name} missing, skipped")
            continue
        transcript = load_transcript(t.txt_path)
        chunks = chunk_by_turn_windowed(transcript.turns)
        if not chunks:
            summary.empty += 1
            print(f"  · {transcript.date} id={transcript.id}: no turns, skipped")
            continue
        n = store.upsert_transcript(transcript.id, chunks)
        summary.indexed += 1
        summary.chunks += n
        print(f"  ✓ {transcript.date} id={transcript.id}: {len(transcript.turns)} turns → {n} chunks")

    if args.no_index:
        print("\nSkipping index build (--no-index).")
    elif summary.chunks:
        print("\nBuilding FTS + scalar indexes ...")
        store.create_indexes()

    print(f"\nTable now holds {store.count()} rows.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="parl_rag.ingest",
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
    opt.add_argument("--data-dir", type=Path, default=config.DATA_DIR,
                     help=f"raw transcripts root (default {config.DATA_DIR})")
    opt.add_argument("--db-path", type=Path, default=config.LANCEDB_PATH,
                     help=f"LanceDB directory (default {config.LANCEDB_PATH})")
    opt.add_argument("--table", default=config.LANCEDB_TABLE,
                     help=f"LanceDB table name (default {config.LANCEDB_TABLE})")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    months = _resolve_months(args)
    summary = Summary()

    span = f"{months[0][0]}-{months[0][1]:02d}"
    if len(months) > 1:
        span += f" … {months[-1][0]}-{months[-1][1]:02d}"
    if args.date:
        span = args.date
    print(f"Ingesting {span}  ({'offline' if args.offline else 'download'} mode)\n")

    if args.offline:
        targets = _gather_offline(args, months, summary)
    else:
        client = ParliamentClient(delay=args.delay)
        targets = _gather_online(args, months, client, summary)

    if not targets:
        print("\nNo transcripts to process.")
        return 0

    _ingest_targets(args, targets, summary)

    print(
        "\nSummary: "
        f"{summary.sittings} sitting(s) seen · {summary.downloaded} downloaded · "
        f"{summary.reused} reused · {summary.placeholders} placeholder(s) · "
        f"{summary.already} already indexed · "
        f"{summary.indexed} indexed ({summary.chunks} chunks) · {summary.empty} empty"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
