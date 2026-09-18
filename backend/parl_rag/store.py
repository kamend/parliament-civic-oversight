from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config
from .chunking import Chunk
from .rerank import Reranker

# Scalar-column metadata we carry on every row (everything except text/vector).
_META_FIELDS = (
    "speaker", "speaker_raw", "role", "party", "modifier",
    "date", "transcript_id", "sitting", "turn_index",
)

# When reranking, fetch at least this many candidates beyond ``k`` so the
# cross-encoder always has headroom to select from (so e.g. k=25 reranks from 40,
# not just 30). Scales the pool with k instead of hard-coding per request size.
_RERANK_MARGIN = 15


@dataclass
class SearchHit:
    """One retrieved chunk plus its scores. ``score`` is what it's ordered by:
    the cross-encoder score when reranked, else the hybrid (RRF) relevance."""

    chunk: Chunk
    score: float
    hybrid_score: float
    reranked: bool
    prior_rank: Optional[int] = None   # 1-based rank before rerank (shows the reshuffle)


def _sql_quote(value: str) -> str:
    """Escape a string for a LanceDB SQL filter literal."""
    return value.replace("'", "''")


def _build_where(
    *, party: str | None, speaker: str | None,
    since: str | None, until: str | None, date: str | None,
) -> str | None:
    """Compose a SQL WHERE clause from the optional filters (all AND-ed)."""
    clauses: list[str] = []
    if party:
        clauses.append(f"party = '{_sql_quote(party)}'")
    if speaker:
        clauses.append(f"speaker = '{_sql_quote(speaker)}'")
    if date:
        clauses.append(f"date = '{_sql_quote(date)}'")
    if since:
        clauses.append(f"date >= '{_sql_quote(since)}'")
    if until:
        clauses.append(f"date <= '{_sql_quote(until)}'")
    return " AND ".join(clauses) if clauses else None


class LanceDBStore:
    """Embedded LanceDB store for parliament chunks: ingest + hybrid search."""

    def __init__(
        self,
        path: Path | str | None = None,
        table_name: str | None = None,
        *,
        embed_model: str | None = None,
        device: str | None = None,
        reranker: Reranker | None = None,
    ):
        self.path = Path(path or config.LANCEDB_PATH)
        self.table_name = table_name or config.LANCEDB_TABLE
        self.embed_model = embed_model or config.EMBED_MODEL
        self.device = device  # None = sentence-transformers auto-selects
        self._db = None
        self._tbl = None
        self._func = None
        self._schema = None
        self._reranker = reranker  # lazily built on first rerank

    # ---- lazy plumbing ------------------------------------------------- #
    @property
    def db(self):
        if self._db is None:
            self.path.mkdir(parents=True, exist_ok=True)
            import lancedb
            self._db = lancedb.connect(self.path)
        return self._db

    @property
    def func(self):
        """The bge-m3 embedding function LanceDB uses for index *and* query."""
        if self._func is None:
            from lancedb.embeddings import get_registry
            kwargs = {"name": self.embed_model, "normalize": True}
            if self.device:
                kwargs["device"] = self.device
            self._func = get_registry().get("sentence-transformers").create(**kwargs)
        return self._func

    def load_embedder(self):
        """Load bge-m3 (once) and pin it in LanceDB's model cache.

        LanceDB never embeds through ``self.func``: on every ``table.add()`` /
        ``search()`` it rebuilds a throwaway embedding function from the table
        metadata. The model cache is keyed on a *weakref* to the instance that
        loaded it, so an entry created by a throwaway dies with it and the next
        call reloads the weights. Loading through ``self.func`` — equal to the
        throwaways, and alive as long as the store — keeps that entry valid.
        Cheap after the first call (cache hit).
        """
        return self.func.get_embedding_model()

    @property
    def schema(self):
        if self._schema is None:
            self._schema = self._build_schema(self.func)
        return self._schema

    @staticmethod
    def _build_schema(func):
        """Build the row schema. ``func.ndims()`` loads the model to learn the
        vector width (1024 for bge-m3), so this is intentionally lazy."""
        from lancedb.pydantic import LanceModel, Vector

        class TurnChunk(LanceModel):
            id: str
            embed_text: str = func.SourceField()        # what we embed (context + text)
            vector: Vector(func.ndims()) = func.VectorField()
            text: str                                   # clean text: display + BM25 FTS
            context: Optional[str] = None
            speaker: Optional[str] = None
            speaker_raw: Optional[str] = None
            role: Optional[str] = None
            party: Optional[str] = None
            modifier: Optional[str] = None
            date: str
            transcript_id: str
            sitting: Optional[str] = None
            turn_index: int
            method: str

        return TurnChunk

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = Reranker()
        return self._reranker

    def exists(self) -> bool:
        return self.table_name in self.db.table_names()

    @property
    def table(self):
        if self._tbl is None:
            if not self.exists():
                raise RuntimeError(
                    f"Table '{self.table_name}' does not exist at {self.path}. "
                    f"Ingest some transcripts first (parl_rag.ingest)."
                )
            self._tbl = self.db.open_table(self.table_name)
        return self._tbl

    # ---- row conversion ------------------------------------------------ #
    @staticmethod
    def _chunk_to_row(c: Chunk) -> dict:
        m = c.metadata
        row = {
            "id": c.id,
            "embed_text": c.embed_text,
            "text": c.text,
            "context": c.context,
            "method": c.method,
        }
        for f in _META_FIELDS:
            row[f] = m.get(f)
        # date is required (BTREE-indexed, non-null) — fall back to empty string.
        row["date"] = row.get("date") or ""
        row["transcript_id"] = str(row.get("transcript_id") or "")
        row["turn_index"] = int(row.get("turn_index") or 0)
        return row

    @staticmethod
    def _row_to_chunk(row: dict) -> Chunk:
        meta = {f: row.get(f) for f in _META_FIELDS}
        return Chunk(
            id=row["id"],
            text=row["text"],
            metadata=meta,
            method=row.get("method") or "turn_windowed",
            context=row.get("context"),
        )

    # ---- ingest -------------------------------------------------------- #
    def add(self, chunks: list[Chunk]) -> int:
        """Add chunks, creating the table (and embedding the rows) on first use."""
        if not chunks:
            return 0
        rows = [self._chunk_to_row(c) for c in chunks]
        self.load_embedder()  # else table.add() reloads the model on every call
        if self.exists():
            self.table.add(rows)
        else:
            self._tbl = self.db.create_table(self.table_name, data=rows, schema=self.schema)
        return len(rows)

    def existing_transcript_ids(self) -> set[str]:
        """The set of ``transcript_id``s already present in the table.

        Lets ingestion skip sittings it has already indexed instead of
        re-embedding them. Empty set if the table doesn't exist yet.
        """
        if not self.exists():
            return set()
        table = self.table.to_lance().to_table(columns=["transcript_id"])
        return {t for t in table.column("transcript_id").to_pylist() if t}

    def upsert_transcript(self, transcript_id: str, chunks: list[Chunk]) -> int:
        """Idempotently (re)load one transcript: delete its existing rows, then
        add. Re-ingesting a date replaces it, never duplicates — robust even if
        chunk ids shift because the source text changed."""
        if self.exists():
            self.table.delete(f"transcript_id = '{_sql_quote(str(transcript_id))}'")
        return self.add(chunks)

    def create_indexes(self) -> None:
        """Build the FTS + scalar indexes. Idempotent (replace=True)."""
        tbl = self.table
        # BM25 full-text index over the clean text, Cyrillic-aware (see this file's docstring).
        tbl.create_fts_index(
            "text",
            use_tantivy=False,
            base_tokenizer="simple",
            lower_case=True,
            stem=False,
            remove_stop_words=False,
            with_position=True,
            replace=True,
        )
        # Low-cardinality categoricals → BITMAP; date range → BTREE.
        for col in ("party", "role", "speaker"):
            tbl.create_scalar_index(col, index_type="BITMAP", replace=True)
        tbl.create_scalar_index("date", index_type="BTREE", replace=True)

    # ---- search -------------------------------------------------------- #
    def search(
        self,
        question: str,
        *,
        k: int = 5,
        party: str | None = None,
        speaker: str | None = None,
        since: str | None = None,
        until: str | None = None,
        date: str | None = None,
        rerank: bool = True,
        overfetch: int = 30,
    ) -> list[SearchHit]:
        """Hybrid (dense + BM25, RRF-fused) → metadata pre-filter → rerank.

        With ``rerank=True`` we over-fetch a candidate pool (at least
        ``overfetch``, and at least ``k`` + ``_RERANK_MARGIN``) and cross-encode it
        down to ``k``. With ``rerank=False`` we return the hybrid top-``k``
        directly. The two stages are also exposed separately
        (:meth:`hybrid_search`, :meth:`rerank_hits`) for the ask graph, which
        runs them as separate nodes.
        """
        candidates = self.hybrid_search(
            question, k=k, party=party, speaker=speaker, since=since, until=until,
            date=date, rerank=rerank, overfetch=overfetch,
        )
        return self.rerank_hits(question, candidates, k=k) if rerank else candidates

    def hybrid_search(
        self,
        question: str,
        *,
        k: int = 5,
        party: str | None = None,
        speaker: str | None = None,
        since: str | None = None,
        until: str | None = None,
        date: str | None = None,
        rerank: bool = True,
        overfetch: int = 30,
    ) -> list[SearchHit]:
        """First stage: the hybrid hits in RRF order, not yet reranked.

        ``rerank`` only sizes the result: True returns the over-fetched candidate
        pool meant for :meth:`rerank_hits`, False returns the final top-``k``.
        """
        where = _build_where(party=party, speaker=speaker, since=since, until=until, date=date)
        fetch = max(k + _RERANK_MARGIN, overfetch) if rerank else k

        self.load_embedder()  # else an un-warmed store reloads the model per query
        q = self.table.search(question, query_type="hybrid")
        if where:
            # prefilter=True: filter BEFORE search, so the candidate pool is the
            # filtered set (exact, uses the scalar indexes). This is the path the
            # research doc flagged to test explicitly — see store smoke test.
            q = q.where(where, prefilter=True)
        hits = []
        for r in q.limit(fetch).to_list():
            score = float(r.get("_relevance_score") or 0.0)
            hits.append(SearchHit(chunk=self._row_to_chunk(r), score=score,
                                  hybrid_score=score, reranked=False))
        return hits

    def rerank_hits(self, question: str, candidates: list[SearchHit], *, k: int = 5) -> list[SearchHit]:
        """Second stage: cross-encode the candidate pool down to the top ``k``."""
        hybrid_by_id = {h.chunk.id: h.hybrid_score for h in candidates}
        reranked = self.reranker.rerank(question, [h.chunk for h in candidates], top_n=k)
        return [
            SearchHit(
                chunk=rc.chunk,
                score=rc.score,
                hybrid_score=hybrid_by_id.get(rc.chunk.id, 0.0),
                reranked=True,
                prior_rank=rc.prior_rank,
            )
            for rc in reranked
        ]

    # ---- introspection ------------------------------------------------- #
    def count(self) -> int:
        return self.table.count_rows() if self.exists() else 0

    def metadata_summary(self) -> dict:
        """Distinct parties & speakers, the date range, and the distinct dates
        that actually have sittings — feeds /api/filters."""
        if not self.exists():
            return {
                "parties": [],
                "speakers": [],
                "min_date": None,
                "max_date": None,
                "sitting_dates": [],
            }
        # Scan only the small scalar columns we need.
        cols = ["party", "speaker", "date"]
        table = self.table.to_lance().to_table(columns=cols)
        parties = sorted({p for p in table.column("party").to_pylist() if p})
        speakers = sorted({s for s in table.column("speaker").to_pylist() if s})
        dates = [d for d in table.column("date").to_pylist() if d]
        sitting_dates = sorted(set(dates))
        return {
            "parties": parties,
            "speakers": speakers,
            "min_date": sitting_dates[0] if sitting_dates else None,
            "max_date": sitting_dates[-1] if sitting_dates else None,
            "sitting_dates": sitting_dates,
        }
