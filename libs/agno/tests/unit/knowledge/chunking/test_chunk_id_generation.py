"""
Minimal tests for chunk ID generation fix.

BUG FIXED: Chunks were getting id=None when documents lacked explicit identifiers,
causing database INSERT failures (PRIMARY KEY violation).

FIX: Added _generate_chunk_id() to ChunkingStrategy base class with 3-tier fallback:
    1. document.id   -> "{id}_{chunk_number}"
    2. document.name -> "{name}_{chunk_number}"
    3. content hash  -> "chunk_{md5[:12]}_{chunk_number}"

This test file verifies:
    1. The fallback logic works correctly
    2. All built-in chunking strategies inherit the fix
    3. Hash-based IDs are deterministic (same content = same ID)
"""

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def doc_with_id():
    """Document with explicit ID - should use ID for chunks."""
    return Document(id="doc123", name="test", content="A" * 10000)


@pytest.fixture
def doc_with_name_only():
    """Document with name but no ID - should fallback to name."""
    return Document(id=None, name="my_document", content="A" * 10000)


@pytest.fixture
def doc_without_identifiers():
    """Document with neither ID nor name - THE BUG CASE - should use content hash."""
    return Document(id=None, name=None, content="A" * 10000)


# =============================================================================
# Core Tests: Verify the 3-tier fallback logic
# =============================================================================


class TestChunkIdFallbackLogic:
    """Test the _generate_chunk_id() fallback hierarchy."""

    def test_tier1_uses_document_id(self, doc_with_id):
        """Tier 1: When document.id exists, use it for chunk IDs."""
        chunker = FixedSizeChunking(chunk_size=5000)
        chunks = chunker.chunk(doc_with_id)

        assert len(chunks) >= 2, "Should produce multiple chunks"
        assert chunks[0].id == "doc123_1"
        assert chunks[1].id == "doc123_2"

    def test_tier2_falls_back_to_name(self, doc_with_name_only):
        """Tier 2: When document.id is None, fallback to document.name."""
        chunker = FixedSizeChunking(chunk_size=5000)
        chunks = chunker.chunk(doc_with_name_only)

        assert len(chunks) >= 2
        assert chunks[0].id == "my_document_1"
        assert chunks[1].id == "my_document_2"

    def test_tier3_falls_back_to_content_hash(self, doc_without_identifiers):
        """Tier 3: When both id and name are None, use content hash.

        THIS IS THE CRITICAL BUG FIX TEST.
        Before: chunks had id=None -> database INSERT failed
        After:  chunks have id="chunk_{hash}_N" -> INSERT succeeds
        """
        chunker = FixedSizeChunking(chunk_size=5000)
        chunks = chunker.chunk(doc_without_identifiers)

        assert len(chunks) >= 2
        # All chunks must have non-None IDs
        assert all(c.id is not None for c in chunks), (
            "BUG: Chunks have None IDs. The _generate_chunk_id() fix is not working."
        )
        # Hash-based IDs follow pattern: chunk_{12-char-hash}_{number}
        assert chunks[0].id.startswith("chunk_"), f"Expected hash-based ID, got: {chunks[0].id}"
        assert "_1" in chunks[0].id
        assert "_2" in chunks[1].id


# =============================================================================
# Integration: Verify all built-in strategies inherit the fix
# =============================================================================


class TestAllStrategiesInheritFix:
    """All chunking strategies should produce valid IDs for documents without identifiers."""

    @pytest.mark.parametrize(
        "chunker_class,name",
        [
            (FixedSizeChunking, "FixedSizeChunking"),
            (RecursiveChunking, "RecursiveChunking"),
            (DocumentChunking, "DocumentChunking"),
        ],
    )
    def test_no_none_ids(self, chunker_class, name, doc_without_identifiers):
        """All strategies must generate non-None IDs for documents without id/name."""
        chunker = chunker_class(chunk_size=5000)
        chunks = chunker.chunk(doc_without_identifiers)

        none_ids = [i for i, c in enumerate(chunks) if c.id is None]
        assert not none_ids, (
            f"{name} produced None IDs at indices {none_ids}. "
            "All strategies should inherit _generate_chunk_id() from base class."
        )


# =============================================================================
# Property: Hash-based IDs are deterministic
# =============================================================================


class TestHashDeterminism:
    """Hash-based IDs should be deterministic for reproducibility."""

    def test_same_content_produces_same_id(self):
        """Same content should always produce the same chunk ID."""
        content = "Deterministic content for testing"
        doc1 = Document(id=None, name=None, content=content)
        doc2 = Document(id=None, name=None, content=content)

        chunker = DocumentChunking(chunk_size=100)
        chunks1 = chunker.chunk(doc1)
        chunks2 = chunker.chunk(doc2)

        assert chunks1[0].id == chunks2[0].id, "Same content should produce same hash-based ID for idempotent upserts"
