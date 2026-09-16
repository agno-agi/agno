"""Pin the observable contract of ChunkingStrategy.clean_text.

Every case below is the behaviour on `main` before the change, so the tests fail on any
rewrite that alters the output rather than only its cost. The Unicode and edge-position
cases are the ones a faster implementation is most likely to get wrong: `" ".join(
text.split())` is the obvious fast rewrite and it silently drops leading and trailing
whitespace.
"""

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document


@pytest.fixture
def clean():
    return FixedSizeChunking().clean_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", ""),
        (" ", " "),
        ("   ", " "),
        ("\n", " "),
        ("\n\n\n", " "),
        ("\t\t", " "),
        ("a b", "a b"),
        ("a  b", "a b"),
        ("a\nb", "a b"),
        ("a\n\n\nb", "a b"),
        ("a\tb", "a b"),
        ("a\r\nb", "a b"),
        ("a\x0bb", "a b"),
        ("a\x0cb", "a b"),
        ("a \t\r\n b", "a b"),
        ("line one\nline two\n\nline four", "line one line two line four"),
    ],
)
def test_every_whitespace_run_collapses_to_one_space(clean, raw, expected):
    assert clean(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (" leading", " leading"),
        ("  leading", " leading"),
        ("\nleading", " leading"),
        ("trailing ", "trailing "),
        ("trailing  ", "trailing "),
        ("trailing\n", "trailing "),
        (" both ", " both "),
        ("\t both \n", " both "),
    ],
)
def test_leading_and_trailing_whitespace_survives_as_a_single_space(clean, raw, expected):
    """`" ".join(text.split())` strips these, which is the trap this case exists for."""
    assert clean(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a b", "a b"),  # NO-BREAK SPACE
        ("a b", "a b"),  # EM SPACE
        ("a b", "a b"),  # OGHAM SPACE MARK
        ("a b", "a b"),  # LINE SEPARATOR
        ("a b", "a b"),  # PARAGRAPH SEPARATOR
        ("ab", "a b"),  # NEXT LINE
        ("a\x1cb", "a b"),  # FILE SEPARATOR
        ("a\x1fb", "a b"),  # UNIT SEPARATOR
        ("a   b", "a b"),
        ("a​b", "a​b"),  # ZERO WIDTH SPACE is not whitespace
        ("a﻿b", "a﻿b"),  # BYTE ORDER MARK is not whitespace
    ],
)
def test_unicode_whitespace_is_treated_exactly_as_re_whitespace_is(clean, raw, expected):
    assert clean(raw) == expected


def test_result_contains_no_whitespace_other_than_single_spaces(clean):
    raw = "para one\n\n\npara two\t\ttabbed\r\ncarriage\x0cff\x0bvt   nbsp"
    out = clean(raw)
    assert "  " not in out
    assert not any(c.isspace() and c != " " for c in out)


CHUNKING_TEXT = (
    "First paragraph with several words in it.\n\n"
    "Second paragraph\twith a tab and   runs of spaces.\r\n"
    "Third paragraph\n\n\nafter blank lines, then a closing sentence. "
)

EXPECTED_CHUNKS = {
    "fixed": [
        ("chunk_21b987d81fd4_1", "First paragraph with several words in it. Second paragraph"),
        ("chunk_77dfa8fb3f1e_2", " with a tab and runs of spaces. Third paragraph after blank"),
        ("chunk_84ec68adc43a_3", " lines, then a closing sentence. "),
    ],
    "fixed_overlap": [
        ("chunk_21b987d81fd4_1", "First paragraph with several words in it. Second paragraph"),
        ("chunk_0bf561079983_2", " paragraph with a tab and runs of spaces. Third paragraph"),
        ("chunk_9b7fd9f99a81_3", " paragraph after blank lines, then a closing sentence. "),
    ],
    "recursive": [
        ("chunk_b21671d25d72_1", "First paragraph with several words in it. "),
        ("chunk_bd1114cb2f4b_2", "Second paragraph with a tab and runs of spaces. "),
        ("chunk_c7502374b7e7_3", "Third paragraph "),
        ("chunk_e952fa55661e_4", "after blank lines, then a closing sentence. "),
    ],
    "document": [
        ("chunk_0a2a32b885d6_1", "First paragraph with several words in it."),
        ("chunk_93fb21929f7d_2", "Second paragraph with a tab and runs of spaces."),
        ("chunk_15e2373ae4c3_3", "Third paragraph\n\nafter blank lines, then a closing sentence."),
    ],
}


@pytest.mark.parametrize(
    "key,strategy",
    [
        ("fixed", FixedSizeChunking(chunk_size=60, overlap=0)),
        ("fixed_overlap", FixedSizeChunking(chunk_size=60, overlap=10)),
        ("recursive", RecursiveChunking(chunk_size=60, overlap=0)),
        ("document", DocumentChunking(chunk_size=60, overlap=0)),
    ],
)
def test_chunk_ids_and_contents_are_stable(key, strategy):
    """clean_text feeds chunk content, and chunk content feeds the chunk id hash, so any
    change in clean_text would silently re-key an already-indexed knowledge base. The
    ids below are the ones produced on main before this change."""
    doc = Document(id=None, name=None, content=CHUNKING_TEXT, meta_data={})
    chunks = strategy.chunk(doc)
    assert [(c.id, c.content) for c in chunks] == EXPECTED_CHUNKS[key]
    for chunk in chunks:
        assert chunk.meta_data["chunk_size"] == len(chunk.content)
