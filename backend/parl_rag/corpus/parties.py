from __future__ import annotations

# --------------------------------------------------------------------------- #
# Bulgarian parliamentary groups.
# Party tags appear in parentheses after a speaker's name, e.g. "ЙОРДАН ИВАНОВ (ДБ):".
# PARTIES maps each canonical abbreviation → its full display name.
# --------------------------------------------------------------------------- #
PARTIES = {
    "ПП": "Продължаваме промяната",
    "ДБ": "Демократична България",
    "ПП-ДБ": "Продължаваме промяната – Демократична България",
    "ПБ": "Прогресивна България",
    "ГЕРБ-СДС": "ГЕРБ-СДС",
    "ВЪЗРАЖДАНЕ": "Възраждане",
    "ДПС": "Движение за права и свободи",
    "БСП": "БСП за България",
    "ИТН": "Има такъв народ",
    "МЕЧ": "Морал, Единство, Чест",
    "НН": "Ново начало",
}

# The same group is written inconsistently across transcripts — sometimes the
# abbreviation "(ПП)", sometimes the full name "(Продължаваме Промяната)", with
# varied casing and dash characters. PARTY_ALIASES maps a canonical abbreviation
# → the alternate spellings seen in the wild, so ingestion can fold every variant
# onto one key (see normalize_party). Add a new spelling here, not in code.
# Matching is case-insensitive and dash-insensitive ("–"/"—"/"-" are equivalent),
# so only genuinely distinct wordings need listing.
PARTY_ALIASES = {
    "ПП": ["Продължаваме промяната"],
    "ПБ": ["Прогресивна България"],
    "ДБ": ["Демократична България"],
    "ДПС": [
        "Движение за права и свободи",
        "Движение за права и свободи - ДПС",
        "ДПС - Ново начало",
    ],
    "ПП-ДБ": ["Продължаваме промяната - Демократична България"],
}


def _party_key(label: str) -> str:
    """Normalize a party label for matching: unify dash glyphs, collapse spaces
    around dashes and runs of whitespace, and casefold. So "Продължаваме
    Промяната – Демократична България" and "...промяната-Демократична България"
    map to the same key."""
    s = label.replace("–", "-").replace("—", "-")
    s = " ".join(s.split())            # collapse whitespace
    s = s.replace(" - ", "-")          # "ГЕРБ - СДС" → "ГЕРБ-СДС"
    return s.casefold()


# Precomputed { normalized spelling -> canonical abbreviation }. Includes every
# canonical key itself plus all its aliases.
_PARTY_CANON = {}
for _canon, _aliases in PARTY_ALIASES.items():
    for _label in (_canon, *_aliases):
        _PARTY_CANON[_party_key(_label)] = _canon
for _canon in PARTIES:
    _PARTY_CANON.setdefault(_party_key(_canon), _canon)


def normalize_party(party: str | None) -> str | None:
    """Fold a raw party tag onto its canonical abbreviation.

    Known spellings (any casing/dash variant) map to the canonical key from
    PARTIES/PARTY_ALIASES; an unrecognized tag is returned trimmed but otherwise
    untouched, so a new group still shows up (just not yet unified) rather than
    being dropped."""
    if not party:
        return None
    party = party.strip()
    return _PARTY_CANON.get(_party_key(party), party or None)

# Role prefixes that precede a name and are NOT part of it. Order matters:
# longer prefixes must be checked first ("ЗАМЕСТНИК-ПРЕДСЕДАТЕЛ" before "ПРЕДСЕДАТЕЛ").
ROLE_PREFIXES = [
    "ЗАМЕСТНИК-ПРЕДСЕДАТЕЛ",
    "ПРЕДСЕДАТЕЛ",
    "МИНИСТЪР-ПРЕДСЕДАТЕЛ",
    "ЗАМЕСТНИК МИНИСТЪР-ПРЕДСЕДАТЕЛ",
    "СЛУЖЕБЕН МИНИСТЪР-ПРЕДСЕДАТЕЛ",
    "МИНИСТЪР",
    "ГЛАВЕН СЕКРЕТАР",
    "ДОКЛАДЧИК",
]
