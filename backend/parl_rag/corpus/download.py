from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterator

import requests

from ..settings import settings

BASE = "https://www.parliament.bg/api/v1"
MODEL = "Pl_StenV"  # plenary stenograms (committee transcripts use a different model)

# Bodies shorter than this are unpublished placeholders, not real transcripts.
PLACEHOLDER_MAX_CHARS = 1000

_USER_AGENT = "parl-rag-ingest/1.0 (+https://www.parliament.bg)"


@dataclass
class Sitting:
    """One daily plenary meeting, as listed by ``archive-period``."""

    id: str          # stenogram id, used to fetch the body (kept as str for metadata parity)
    date: str        # "YYYY-MM-DD"
    year: int
    month: int


@dataclass
class DownloadResult:
    """Outcome of saving one sitting to disk."""

    sitting: Sitting
    txt_path: Path
    chars: int           # length of the raw HTML body
    placeholder: bool    # True when the body is an unpublished stub
    skipped: bool = False  # True when files already existed and we didn't refetch


def html_to_text(html: str) -> str:
    """Crude but adequate HTML → plain text for a transcript body.

    Preserves the paragraph structure :mod:`parl_rag.corpus.parsing` relies on: ``<br>``
    becomes a single newline, ``</p>`` a blank line (paragraph break), then all
    remaining tags are dropped and entities unescaped.
    """
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ParliamentClient:
    """Pooled HTTP client for the parliament.bg stenogram API."""

    def __init__(
        self,
        *,
        base_url: str = BASE,
        retries: int = 3,
        backoff: float = 2.0,
        delay: float = 0.5,
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.backoff = backoff      # seconds, multiplied by attempt number
        self.delay = delay          # polite pause between body downloads
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    # ---- raw API calls ------------------------------------------------- #
    def _get_json(self, path: str):
        """GET ``{base}/{path}`` and parse JSON, retrying with linear backoff."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as err:
                last_err = err
                if attempt < self.retries:
                    time.sleep(self.backoff * attempt)
        raise RuntimeError(f"Failed to fetch {url}: {last_err}")

    def list_months(self) -> list[dict]:
        """Years → months that contain plenary transcripts (the calendar)."""
        data = self._get_json(f"archive-list/bg/{MODEL}/0/0")
        return data if isinstance(data, list) else []

    def list_sittings(self, year: int, month: int) -> list[Sitting]:
        """The sittings in one month, oldest first.

        The API returns newest-first; we sort ascending so ingest processes a
        month chronologically (and re-runs are deterministic).
        """
        data = self._get_json(f"archive-period/bg/{MODEL}/{year}/{month}/0/0")
        rows = data if isinstance(data, list) else []
        sittings = [
            Sitting(id=str(r["t_id"]), date=r.get("t_date", ""), year=year, month=month)
            for r in rows
            if r.get("t_id") is not None
        ]
        return sorted(sittings, key=lambda s: (s.date, s.id))

    def fetch_transcript(self, sten_id: str | int) -> dict:
        """The full transcript record for one stenogram id (incl. HTML body)."""
        return self._get_json(f"pl-sten/{sten_id}")

    # ---- persistence --------------------------------------------------- #
    @staticmethod
    def month_dir(data_dir: Path, year: int, month: int) -> Path:
        return data_dir / f"{year}-{month:02d}"

    def save_sitting(
        self,
        sitting: Sitting,
        *,
        data_dir: Path | None = None,
        skip_existing: bool = False,
    ) -> DownloadResult:
        """Fetch one sitting and write its json/html/txt files.

        With ``skip_existing`` a sitting whose ``.txt`` is already on disk (and is
        not a placeholder) is left untouched — no network call. Placeholders are
        always refetched, since the real transcript may have been published since.
        """
        data_dir = data_dir or settings.data_dir
        out_dir = self.month_dir(data_dir, sitting.year, sitting.month)
        stem = f"{sitting.date}_{sitting.id}"
        txt_path = out_dir / f"{stem}.txt"

        if skip_existing and txt_path.exists():
            existing = txt_path.read_text(encoding="utf-8")
            if len(existing) >= PLACEHOLDER_MAX_CHARS:
                return DownloadResult(
                    sitting=sitting, txt_path=txt_path, chars=len(existing),
                    placeholder=False, skipped=True,
                )

        doc = self.fetch_transcript(sitting.id)
        body = doc.get("Pl_Sten_body", "") or ""

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{stem}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / f"{stem}.html").write_text(body, encoding="utf-8")
        (out_dir / f"{stem}.txt").write_text(html_to_text(body), encoding="utf-8")

        if self.delay:
            time.sleep(self.delay)

        return DownloadResult(
            sitting=sitting,
            txt_path=txt_path,
            chars=len(body),
            placeholder=len(body) < PLACEHOLDER_MAX_CHARS,
        )


def iter_months(since: tuple[int, int], until: tuple[int, int]) -> Iterator[tuple[int, int]]:
    """Yield ``(year, month)`` from ``since`` to ``until`` inclusive."""
    y, m = since
    ey, em = until
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1
