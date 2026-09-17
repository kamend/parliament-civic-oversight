"""Tests for parl_rag.chunking._pack_sentences.

The function packs sentences into chunks of up to ``max_chars``, carries a
character overlap across chunk boundaries, and merges a short leftover tail
(< 200 chars) into the previous chunk instead of emitting a fragment.

Sentences here are synthetic with exact lengths so every packing decision is
deterministic and the expected chunks can be written out literally.
"""

from parl_rag.chunking import _pack_sentences


def sent(i: int, length: int, terminator: str = ".") -> str:
    """A sentence of exactly ``length`` chars: 's<i> xxx...x<terminator>'."""
    body = f"s{i:02d} " + "x" * length
    return body[: length - 1] + terminator

def test_text_under_max_chars_returns_single_chunk():
    text = " ".join(sent(i, 80) for i in range(3))  # 242 chars
    assert _pack_sentences(text, max_chars=1000, overlap_chars=0) == [text]


def test_packs_whole_sentences_up_to_max_chars():
    sents = [sent(i, 100) for i in range(10)]
    text = " ".join(sents)

    out = _pack_sentences(text, max_chars=350, overlap_chars=0)

    # 3 sentences fit per chunk (302 chars); the lone 10th sentence is a
    # short tail (100 < 200) and gets merged into the last chunk.
    assert out == [
        " ".join(sents[0:3]),
        " ".join(sents[3:6]),
        " ".join(sents[6:10]),
    ]
    # With no overlap the chunks reconstruct the original text exactly.
    assert " ".join(out) == text


def test_short_tail_merged_into_last_chunk():
    sents = [sent(0, 250), sent(1, 250), sent(2, 250), sent(3, 100)]
    text = " ".join(sents)

    out = _pack_sentences(text, max_chars=300, overlap_chars=0)

    assert len(out) == 3
    assert out[-1] == sents[2] + " " + sents[3]


def test_long_tail_kept_as_own_chunk():
    sents = [sent(i, 250) for i in range(4)]
    text = " ".join(sents)

    out = _pack_sentences(text, max_chars=300, overlap_chars=0)

    # Each 250-char sentence overflows a 300-char budget on its own, and the
    # 250-char tail is >= 200 so it stays a separate chunk.
    assert out == sents


def test_overlap_carried_across_chunks():
    overlap = 50
    sents = [sent(i, 100) for i in range(10)]
    text = " ".join(sents)

    out = _pack_sentences(text, max_chars=350, overlap_chars=overlap)

    assert len(out) > 1
    # Each chunk after the first starts with the tail of the previous one, so
    # a fact split across the boundary survives in both chunks.
    for prev, nxt in zip(out, out[1:]):
        assert nxt.startswith(prev[-overlap:].lstrip())
    # Overlap duplicates text but loses nothing: every sentence is present.
    joined = " ".join(out)
    for s in sents:
        assert s in joined


def test_splits_on_various_terminators():
    # The sentence regex must split after '.', '!', '?' and '…' alike.
    sents = [("х" * 219) + p for p in (".", "!", "?", "…")]
    text = " ".join(sents)

    out = _pack_sentences(text, max_chars=230, overlap_chars=0)

    assert out == sents


def test_single_long_sentence_is_not_split():
    # No sentence boundary to cut on: the chunk exceeds max_chars rather than
    # being cut mid-word.
    text = "х" * 1500 + "."
    assert _pack_sentences(text, max_chars=400, overlap_chars=50) == [text]
