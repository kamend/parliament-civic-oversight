from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .corpus.chunking import chunk_by_turn_windowed
from .corpus.download import PLACEHOLDER_MAX_CHARS, ParliamentClient, Sitting
from .corpus.parsing import load_transcript
from .retrieval.store import LanceDBStore
from .settings import settings

Month = tuple[int, int]


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
# Locating transcripts (online: download; offline: scan disk)
# --------------------------------------------------------------------------- #
def gather_online(
    months: list[Month], client: ParliamentClient, summary: Summary, *,
    date: str | None = None, data_dir: Path | None = None, skip_existing: bool = False,
) -> list[Target]:
    """List each month's sittings via the API and download them to disk.
    ``date`` narrows the month to a single sitting day (YYYY-MM-DD)."""
    date_filter = date
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
            res = client.save_sitting(s, data_dir=data_dir, skip_existing=skip_existing)
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


def gather_offline(
    months: list[Month], summary: Summary, *,
    date: str | None = None, data_dir: Path | None = None,
) -> list[Target]:
    """Find already-downloaded ``.txt`` files for the requested months on disk."""
    date_filter = date
    data_dir = data_dir or settings.data_dir
    targets: list[Target] = []
    for year, month in months:
        month_dir = ParliamentClient.month_dir(data_dir, year, month)
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
def ingest_targets(
    targets: list[Target], store: LanceDBStore, summary: Summary, *,
    reset: bool = False, force: bool = False, build_indexes: bool = True,
) -> None:
    """Parse → chunk → upsert every non-placeholder target into LanceDB.

    ``reset`` drops the table first (full rebuild). ``force`` re-ingests
    sittings already in the store. ``build_indexes=False`` loads rows but skips
    the FTS/scalar index build.
    """
    if reset and store.exists():
        print(f"\nReset: dropping table '{store.table_name}'")
        store.db.drop_table(store.table_name)

    to_index = [t for t in targets if not t.placeholder]

    # By default, skip sittings already in the store — re-embedding and
    # re-indexing transcripts that haven't changed is wasteful. --force re-ingests
    # them anyway (replacing their rows); --reset already cleared the table above.
    if not force:
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

    store.load_embedder()

    for t in to_index:
        if not t.txt_path.exists():
            print(f"  ! {t.sitting.date} id={t.sitting.id}: {t.txt_path.name} missing, skipped")
            continue
        transcript = load_transcript(t.txt_path)
        chunks = chunk_by_turn_windowed(transcript.turns, min_words=settings.min_turn_words)
        if not chunks:
            summary.empty += 1
            print(f"  · {transcript.date} id={transcript.id}: no turns, skipped")
            continue
        n = store.upsert_transcript(transcript.id, chunks)
        summary.indexed += 1
        summary.chunks += n
        print(f"  ✓ {transcript.date} id={transcript.id}: {len(transcript.turns)} turns → {n} chunks")

    if not build_indexes:
        print("\nSkipping index build (--no-index).")
    elif summary.chunks:
        print("\nBuilding FTS + scalar indexes ...")
        store.create_indexes()

    print(f"\nTable now holds {store.count()} rows.")


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run(
    months: list[Month], *,
    date: str | None = None,
    offline: bool = False,
    skip_existing: bool = False,
    reset: bool = False,
    force: bool = False,
    build_indexes: bool = True,
    delay: float = 0.5,
    data_dir: Path | None = None,
    db_path: Path | None = None,
    table: str | None = None,
) -> Summary:
    """Locate the transcripts for ``months`` (download them, or with ``offline``
    scan the disk), then index them. Returns the run's counters."""
    summary = Summary()
    if offline:
        targets = gather_offline(months, summary, date=date, data_dir=data_dir)
    else:
        client = ParliamentClient(delay=delay)
        targets = gather_online(months, client, summary, date=date, data_dir=data_dir,
                                skip_existing=skip_existing)

    if not targets:
        print("\nNo transcripts to process.")
        return summary

    store = LanceDBStore(path=db_path, table_name=table)
    ingest_targets(targets, store, summary, reset=reset, force=force, build_indexes=build_indexes)
    return summary


if __name__ == "__main__":  # keeps `python -m parl_rag.ingest ...` working
    from .cli import main

    sys.exit(main(["ingest", *sys.argv[1:]]))
