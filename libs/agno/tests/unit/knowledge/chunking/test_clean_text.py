"""Tests for ChunkingStrategy.clean_text() newline-preservation behavior."""

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.document.base import Document


class TestCleanTextPreservesNewlines:
    """clean_text() collapses multiple newlines to one but must not erase them entirely."""

    def test_multiple_newlines_collapse_to_single_newline(self):
        strategy = FixedSizeChunking()
        text = "First paragraph.\n\n\nSecond paragraph.\n\nThird paragraph."

        cleaned = strategy.clean_text(text)

        assert "\n" in cleaned
        assert cleaned == "First paragraph.\nSecond paragraph.\nThird paragraph."

    def test_single_newline_is_preserved(self):
        strategy = FixedSizeChunking()
        text = "AAAAAAAAAA\nBBBBBBBBBB"

        cleaned = strategy.clean_text(text)

        assert cleaned == "AAAAAAAAAA\nBBBBBBBBBB"


class TestFixedSizeChunkingSplitsAtNewlines:
    """FixedSizeChunking checks for '\\n' as a word-boundary split point (fixed.py),
    which requires clean_text() to actually preserve newlines in its output."""

    def test_splits_at_newline_boundary_not_mid_word(self):
        text = "AAAAAAAAAA\nBBBBBBBBBB"

        doc = Document(id="test", name="test", content=text)
        chunker = FixedSizeChunking(chunk_size=15, overlap=0)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 2
        assert chunks[0].content == "AAAAAAAAAA"
        assert chunks[1].content == "\nBBBBBBBBBB"
