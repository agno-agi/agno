"""
Tests for chunk ID generation across chunking strategies.

Bug Report: KNOWLEDGE-002
- RecursiveChunking was missing the `elif document.name` fallback for chunk IDs
- FixedSizeChunking has this fallback
- This caused chunks to have id=None when document has name but no id
"""

import pytest

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document


def generate_long_content(length: int = 15000) -> str:
    """Generate content long enough to produce multiple chunks."""
    return "A" * length


class TestChunkIdWithDocumentId:
    """Chunking strategies should use document.id for chunk IDs when available."""

    @pytest.fixture
    def document_with_id(self):
        """Document with explicit ID."""
        return Document(
            id="doc123",
            name="test_document",
            content=generate_long_content(),
            meta_data={},
        )

    def test_fixed_chunking_uses_document_id(self, document_with_id):
        """FixedSizeChunking should use document.id for chunk IDs."""
        chunker = FixedSizeChunking(chunk_size=5000)
        chunks = chunker.chunk(document_with_id)

        assert len(chunks) >= 2
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id == "doc123_1"
        assert chunks[1].id == "doc123_2"

    def test_recursive_chunking_uses_document_id(self, document_with_id):
        """RecursiveChunking should use document.id for chunk IDs."""
        chunker = RecursiveChunking(chunk_size=5000)
        chunks = chunker.chunk(document_with_id)

        assert len(chunks) >= 2
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id == "doc123_1"
        assert chunks[1].id == "doc123_2"


class TestChunkIdWithDocumentNameOnly:
    """Chunking strategies should fall back to document.name when document.id is None.

    This is the critical test for Bug KNOWLEDGE-002.
    """

    @pytest.fixture
    def document_with_name_only(self):
        """Document with name but no explicit ID (common case for file-based documents)."""
        return Document(
            id=None,
            name="my_document",
            content=generate_long_content(),
            meta_data={},
        )

    def test_fixed_chunking_falls_back_to_document_name(self, document_with_name_only):
        """FixedSizeChunking should use document.name as fallback for chunk IDs."""
        chunker = FixedSizeChunking(chunk_size=5000)
        chunks = chunker.chunk(document_with_name_only)

        assert len(chunks) >= 2
        assert all(c.id is not None for c in chunks), "All chunks should have non-None IDs"
        assert chunks[0].id == "my_document_1"
        assert chunks[1].id == "my_document_2"

    def test_recursive_chunking_falls_back_to_document_name(self, document_with_name_only):
        """RecursiveChunking should use document.name as fallback for chunk IDs.

        Bug Report: KNOWLEDGE-002
        This test was failing because RecursiveChunking was missing the
        `elif document.name` clause that FixedSizeChunking has.
        """
        chunker = RecursiveChunking(chunk_size=5000)
        chunks = chunker.chunk(document_with_name_only)

        assert len(chunks) >= 2
        assert all(c.id is not None for c in chunks), (
            "All chunks should have non-None IDs. "
            "RecursiveChunking should fall back to document.name when document.id is None."
        )
        assert chunks[0].id == "my_document_1"
        assert chunks[1].id == "my_document_2"


class TestChunkIdConsistency:
    """Both chunking strategies should produce consistent ID patterns."""

    @pytest.fixture
    def document_with_name_only(self):
        """Document with name but no ID."""
        return Document(
            id=None,
            name="test_file",
            content=generate_long_content(),
            meta_data={},
        )

    def test_both_strategies_produce_non_none_ids(self, document_with_name_only):
        """Both FixedSize and Recursive chunking should produce non-None chunk IDs."""
        strategies = [
            ("FixedSizeChunking", FixedSizeChunking(chunk_size=5000)),
            ("RecursiveChunking", RecursiveChunking(chunk_size=5000)),
        ]

        for strategy_name, chunker in strategies:
            chunks = chunker.chunk(document_with_name_only)
            assert len(chunks) >= 2, f"{strategy_name} should produce multiple chunks"

            none_ids = [i for i, c in enumerate(chunks) if c.id is None]
            assert not none_ids, (
                f"{strategy_name} produced chunks with None IDs at indices {none_ids}. "
                f"Expected all chunks to have IDs based on document.name='test_file'."
            )

    def test_both_strategies_use_same_id_format(self, document_with_name_only):
        """Both strategies should use the same ID format: {name}_{chunk_number}."""
        strategies = [
            ("FixedSizeChunking", FixedSizeChunking(chunk_size=5000)),
            ("RecursiveChunking", RecursiveChunking(chunk_size=5000)),
        ]

        for strategy_name, chunker in strategies:
            chunks = chunker.chunk(document_with_name_only)

            # First chunk should be named {name}_1
            assert chunks[0].id == "test_file_1", (
                f"{strategy_name} first chunk ID should be 'test_file_1', got '{chunks[0].id}'"
            )


class TestChunkIdWithNoIdentifiers:
    """Test behavior when document has neither id nor name.

    After the bug fix, all chunking strategies generate hash-based IDs
    for documents without id or name, ensuring chunks always have valid IDs.
    """

    @pytest.fixture
    def document_without_identifiers(self):
        """Document with neither id nor name."""
        return Document(
            id=None,
            name=None,
            content=generate_long_content(),
            meta_data={},
        )

    def test_fixed_chunking_generates_hash_ids(self, document_without_identifiers):
        """FixedSizeChunking should generate hash-based IDs for documents without id/name."""
        chunker = FixedSizeChunking(chunk_size=5000)
        chunks = chunker.chunk(document_without_identifiers)

        assert len(chunks) >= 2
        # After fix: All chunks should have hash-based IDs, not None
        assert all(c.id is not None for c in chunks), (
            "FixedSizeChunking should generate hash-based IDs for documents without id/name"
        )
        # Hash-based IDs follow pattern: chunk_{12-char-hash}_{number}
        assert chunks[0].id.startswith("chunk_"), f"Expected hash-based ID, got: {chunks[0].id}"

    def test_recursive_chunking_generates_hash_ids(self, document_without_identifiers):
        """RecursiveChunking should generate hash-based IDs for documents without id/name."""
        chunker = RecursiveChunking(chunk_size=5000)
        chunks = chunker.chunk(document_without_identifiers)

        assert len(chunks) >= 2
        # After fix: All chunks should have hash-based IDs, not None
        assert all(c.id is not None for c in chunks), (
            "RecursiveChunking should generate hash-based IDs for documents without id/name"
        )
        # Hash-based IDs follow pattern: chunk_{12-char-hash}_{number}
        assert chunks[0].id.startswith("chunk_"), f"Expected hash-based ID, got: {chunks[0].id}"
