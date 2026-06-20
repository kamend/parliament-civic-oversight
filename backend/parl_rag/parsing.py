from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from . import config

# --------------------------------------------------------------------------- #
# Regexes
# --------------------------------------------------------------------------- #
# A speaker line: leading uppercase Cyrillic/Latin "name" (which may include the
# role prefix and hyphens/spaces/dots), an optional "(...)" tag, then ":" + space.
# We require the name to be reasonably long to avoid matching stray acronyms.
_SPEAKER_RE = re.compile(
    r"^([А-ЯA-ZЁЇІ][А-ЯA-ZЁЇІ\- .]{2,}?)"   # the all-caps name (+ role prefix)
    r"(?:\s*\(([^)]*)\))?"                      # optional (party[, modifier])
    r":\s"                                       # the colon that ends the header
)

# Vote tally line, e.g.:
#   "Гласували 230 народни представители: за 218, против 12, въздържали се няма."
# "няма" means zero. Numbers are Arabic digits.
_VOTE_RE = re.compile(
    r"Гласували\s+(\d+)\s+народни представители:\s*"
    r"за\s+(\d+|няма),\s*против\s+(\d+|няма),\s*въздържали се\s+(\d+|няма)"
)


def _to_int(tok: str) -> int:
    return 0 if tok == "няма" else int(tok)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Turn:
    """One contiguous block of speech by a single speaker."""

    speaker: str            # full name without role prefix, e.g. "Михаела Доцова" (Title Case)
    speaker_raw: str        # exactly as printed, e.g. "ПРЕДСЕДАТЕЛ МИХАЕЛА ДОЦОВА"
    role: str | None        # "ПРЕДСЕДАТЕЛ", "МИНИСТЪР", ... or None for a regular MP
    party: str | None       # "ДБ", "ГЕРБ-СДС", ... or None (chairs/ministers usually have none)
    modifier: str | None    # e.g. "от място" (heckling from the floor) or None
    text: str               # the spoken text (header line stripped)
    transcript_id: str      # e.g. "11122"
    date: str               # "YYYY-MM-DD"
    sitting: str | None     # sitting description from the header, if available
    index: int              # 0-based position of this turn within the transcript

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class Vote:
    """A recorded vote tally."""

    text: str
    total: int
    yes: int
    no: int
    abstain: int
    transcript_id: str
    date: str

    @property
    def passed(self) -> bool:
        return self.yes > (self.no + self.abstain)


@dataclass
class Transcript:
    """A full daily plenary sitting."""

    id: str
    date: str
    header: str             # Pl_Sten_sub: assembly no., sitting no., date, opening time
    path: Path
    turns: list[Turn] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)

    @property
    def speakers(self) -> set[str]:
        return {t.speaker for t in self.turns}


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _split_speaker_header(name_raw: str) -> tuple[str, str | None]:
    """Split a raw header name into (display_name, role).

    "ПРЕДСЕДАТЕЛ МИХАЕЛА ДОЦОВА" -> ("Михаела Доцова", "ПРЕДСЕДАТЕЛ")
    "ЙОРДАН ИВАНОВ"              -> ("Йордан Иванов", None)
    """
    role: str | None = None
    name = name_raw.strip()
    for prefix in config.ROLE_PREFIXES:
        if name.startswith(prefix):
            role = prefix
            name = name[len(prefix):].strip()
            break
    # Title-case the (Cyrillic) name for nicer display & stable metadata keys.
    display = " ".join(w.capitalize() for w in name.split()) if name else name_raw.title()
    return display, role


def _split_paren(paren: str | None) -> tuple[str | None, str | None]:
    """Split a parenthetical "(ПБ, от място)" into (party, modifier).

    The party is folded onto its canonical abbreviation (see
    :func:`config.normalize_party`) so the same group, however the transcript
    spells it ("ПП" vs "Продължаваме Промяната"), lands under one key."""
    if not paren:
        return None, None
    parts = [p.strip() for p in paren.split(",") if p.strip()]
    if not parts:
        return None, None
    party = config.normalize_party(parts[0])
    modifier = ", ".join(parts[1:]) or None
    return party, modifier


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def parse_turns(text: str, *, transcript_id: str, date: str, sitting: str | None) -> list[Turn]:
    """Turn raw transcript text into a list of speaker turns.

    Continuation paragraphs (no speaker header) are appended to the current turn.
    Text before the first speaker header (chair preamble, secretaries list) is
    ignored for turn purposes — it carries no attribution.
    """
    turns: list[Turn] = []
    current: Turn | None = None
    idx = 0

    for para in _paragraphs(text):
        m = _SPEAKER_RE.match(para)
        if m:
            name_raw, paren = m.group(1).strip(), m.group(2)
            display, role = _split_speaker_header(name_raw)
            party, modifier = _split_paren(paren)
            body = para[m.end():].strip()
            current = Turn(
                speaker=display,
                speaker_raw=name_raw,
                role=role,
                party=party,
                modifier=modifier,
                text=body,
                transcript_id=transcript_id,
                date=date,
                sitting=sitting,
                index=idx,
            )
            turns.append(current)
            idx += 1
        elif current is not None:
            # Continuation of the current speaker (or a stage direction inside it).
            current.text += "\n" + para
    return turns


def has_turns(text: str) -> bool:
    """True if the text contains at least one speaker turn.

    A real published transcript always has speaker headers; an *unpublished*
    sitting carries only parliament.bg's boilerplate notice ("the stenographic
    protocols are published within 7 days…") and so parses to zero turns. This is
    the signal we use to tell "transcript ready" from "not uploaded yet".
    """
    return any(_SPEAKER_RE.match(p) for p in _paragraphs(text))


def parse_votes(text: str, *, transcript_id: str, date: str) -> list[Vote]:
    votes: list[Vote] = []
    for m in _VOTE_RE.finditer(text):
        total, yes, no, abstain = (m.group(1), m.group(2), m.group(3), m.group(4))
        votes.append(
            Vote(
                text=m.group(0),
                total=int(total),
                yes=_to_int(yes),
                no=_to_int(no),
                abstain=_to_int(abstain),
                transcript_id=transcript_id,
                date=date,
            )
        )
    return votes


def _sitting_from_header(header: str) -> str | None:
    """The JSON 'Pl_Sten_sub' header looks like:
    'ПЕТДЕСЕТ И ВТОРО НАРОДНО СЪБРАНИЕ, ВТОРО ЗАСЕДАНИЕ, София, ...'
    We keep the whole thing; it's short and useful as metadata."""
    return header.strip() or None


def load_transcript(txt_path: Path) -> Transcript:
    """Load one transcript from its .txt file (and sibling .json for metadata)."""
    stem = txt_path.stem                      # "2026-05-07_11122"
    date, _, tid = stem.partition("_")
    text = txt_path.read_text(encoding="utf-8")

    header = ""
    json_path = txt_path.with_suffix(".json")
    if json_path.exists():
        try:
            meta = json.loads(json_path.read_text(encoding="utf-8"))
            header = meta.get("Pl_Sten_sub", "") or ""
            # Prefer the authoritative date from the JSON when present.
            date = meta.get("Pl_Sten_date", date) or date
        except (json.JSONDecodeError, OSError):
            pass

    sitting = _sitting_from_header(header)
    return Transcript(
        id=tid,
        date=date,
        header=header,
        path=txt_path,
        turns=parse_turns(text, transcript_id=tid, date=date, sitting=sitting),
        votes=parse_votes(text, transcript_id=tid, date=date),
    )


def iter_transcript_files(data_dir: Path | None = None) -> Iterator[Path]:
    data_dir = data_dir or config.DATA_DIR
    yield from sorted(data_dir.glob("*/*.txt"))


def load_all_transcripts(data_dir: Path | None = None) -> list[Transcript]:
    """Load every transcript. ~26 files / ~9.5MB — fits comfortably in memory."""
    return [load_transcript(p) for p in iter_transcript_files(data_dir)]


def all_turns(transcripts: list[Transcript] | None = None) -> list[Turn]:
    transcripts = transcripts if transcripts is not None else load_all_transcripts()
    return [t for tr in transcripts for t in tr.turns]
