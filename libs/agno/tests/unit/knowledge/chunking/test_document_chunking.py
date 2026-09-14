"""
Tests for DocumentChunking size enforcement on paragraphs without usable sentence boundaries.
"""

import re

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.document.base import Document


def _words(count: int) -> list:
    return [f"word{index:03d}" for index in range(count)]


def _words_in_order(chunks) -> list:
    return re.findall(r"word\d{3}", " ".join(chunk.content for chunk in chunks))


class TestDocumentChunkingOversizedSentences:
    """Chunks must never exceed chunk_size (before overlap), even without sentence boundaries."""

    def test_paragraph_without_sentence_boundaries_is_split(self):
        words = _words(300)
        doc = Document(id="doc", name="doc", content=" ".join(words))
        chunker = DocumentChunking(chunk_size=200, overlap=0)

        chunks = chunker.chunk(doc)

        assert len(chunks) > 1
        assert all(len(chunk.content) <= 200 for chunk in chunks)
        assert _words_in_order(chunks) == words

    def test_single_long_sentence_inside_a_paragraph_is_split(self):
        words = _words(60)
        long_sentence = " ".join(words) + "."
        content = "Short first sentence. " + long_sentence + " Short last sentence."
        doc = Document(id="doc", name="doc", content=content)
        chunker = DocumentChunking(chunk_size=120, overlap=0)

        chunks = chunker.chunk(doc)

        assert all(len(chunk.content) <= 120 for chunk in chunks)
        assert _words_in_order(chunks) == words
        assert chunks[0].content.startswith("Short first sentence.")
        assert chunks[-1].content.endswith("Short last sentence.")

    def test_single_token_longer_than_chunk_size_is_hard_cut(self):
        doc = Document(id="doc", name="doc", content="x" * 450)
        chunker = DocumentChunking(chunk_size=100, overlap=0)

        chunks = chunker.chunk(doc)

        assert [len(chunk.content) for chunk in chunks] == [100, 100, 100, 100, 50]
        assert "".join(chunk.content for chunk in chunks) == "x" * 450

    def test_chunk_numbers_and_ids_stay_sequential(self):
        doc = Document(id="doc", name="doc", content=" ".join(_words(300)))
        chunker = DocumentChunking(chunk_size=200, overlap=0)

        chunks = chunker.chunk(doc)

        assert [chunk.meta_data["chunk"] for chunk in chunks] == list(range(1, len(chunks) + 1))
        assert [chunk.id for chunk in chunks] == [f"doc_{number}" for number in range(1, len(chunks) + 1)]
        assert all(chunk.meta_data["chunk_size"] == len(chunk.content) for chunk in chunks)

    def test_overlap_is_still_applied_after_splitting(self):
        doc = Document(id="doc", name="doc", content=" ".join(_words(300)))
        chunker = DocumentChunking(chunk_size=200, overlap=20)

        chunks = chunker.chunk(doc)

        assert len(chunks) > 1
        for previous, current in zip(chunks, chunks[1:]):
            assert current.content.startswith(previous.content[-20:])

    def test_paragraphs_within_chunk_size_are_unchanged(self):
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        doc = Document(id="doc", name="doc", content=content)
        chunker = DocumentChunking(chunk_size=40, overlap=0)

        chunks = chunker.chunk(doc)

        assert [chunk.content for chunk in chunks] == [
            "First paragraph.\n\nSecond paragraph.",
            "Third paragraph.",
        ]

    def test_join_separator_is_counted_towards_chunk_size(self):
        # Pieces whose lengths add up exactly to chunk_size must not exceed it once joined with a space
        doc = Document(id="doc", name="doc", content="aaaaaa bbbb qqqqqqqqqqq")
        chunker = DocumentChunking(chunk_size=10, overlap=0)

        chunks = chunker.chunk(doc)

        assert all(len(chunk.content) <= 10 for chunk in chunks)
        assert " ".join(chunk.content for chunk in chunks).split(" ") == ["aaaaaa", "bbbb", "qqqqqqqqqq", "q"]

    def test_non_positive_chunk_size_is_rejected(self):
        with pytest.raises(ValueError):
            DocumentChunking(chunk_size=0)
        with pytest.raises(ValueError):
            DocumentChunking(chunk_size=-5)
