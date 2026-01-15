"""
Tests for chunk ID generation fallback across ALL chunking strategies.

Bug Reports: C9, C10 (and MarkdownChunking)
- SemanticChunking was missing ID fallback for documents without id/name
- CodeChunking was missing ID fallback for documents without id/name
- MarkdownChunking was missing ID fallback for documents without id/name

FIX: All chunking strategies now use _generate_chunk_id() which:
1. Uses document.id if available
2. Falls back to document.name if no id
3. Falls back to content hash if no id or name

This ensures chunks ALWAYS have a valid ID for database insertion.
"""

import pytest

from agno.knowledge.document.base import Document

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def document_with_id():
    """Document with explicit ID."""
    return Document(
        id="doc123",
        name="test_document",
        content="First sentence here. Second sentence here. Third sentence. Fourth one. Fifth sentence.",
        meta_data={},
    )


@pytest.fixture
def document_with_name_only():
    """Document with name but no explicit ID."""
    return Document(
        id=None,
        name="my_document",
        content="First sentence here. Second sentence here. Third sentence. Fourth one. Fifth sentence.",
        meta_data={},
    )


@pytest.fixture
def document_without_identifiers():
    """Document with neither id nor name - the edge case that caused the bug."""
    return Document(
        id=None,
        name=None,
        content="First sentence here. Second sentence here. Third sentence. Fourth one. Fifth sentence.",
        meta_data={},
    )


# =============================================================================
# SemanticChunking Tests
# =============================================================================


class TestSemanticChunkingIdFallback:
    """Test SemanticChunking ID generation fallback.

    Bug Report: C10
    SemanticChunking was generating None chunk IDs for documents without id/name.
    """

    @pytest.fixture
    def chunker(self):
        """Create SemanticChunking instance."""
        try:
            from agno.knowledge.chunking.semantic import SemanticChunking

            return SemanticChunking()
        except ImportError:
            pytest.skip("chonkie not installed")

    def test_uses_document_id(self, chunker, document_with_id):
        """Should use document.id for chunk IDs when available."""
        chunks = chunker.chunk(document_with_id)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id.startswith("doc123_")

    def test_falls_back_to_document_name(self, chunker, document_with_name_only):
        """Should fall back to document.name when document.id is None."""
        chunks = chunker.chunk(document_with_name_only)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), "All chunks should have non-None IDs"
        assert chunks[0].id.startswith("my_document_")

    def test_falls_back_to_content_hash(self, chunker, document_without_identifiers):
        """Should fall back to content hash when both id and name are None.

        This is the critical test for Bug C10.
        Before fix: chunks had id=None
        After fix: chunks have id=chunk_{hash}_{number}
        """
        chunks = chunker.chunk(document_without_identifiers)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), (
            "SemanticChunking should generate hash-based IDs for documents without id/name. "
            "Bug C10: SemanticChunking was returning None IDs."
        )
        # Hash-based IDs follow pattern: chunk_{12-char-hash}_{number}
        assert chunks[0].id.startswith("chunk_"), f"Expected hash-based ID, got: {chunks[0].id}"


# =============================================================================
# CodeChunking Tests
# =============================================================================


class TestCodeChunkingIdFallback:
    """Test CodeChunking ID generation fallback.

    Bug Report: C9
    CodeChunking was generating None chunk IDs for documents without id/name.
    """

    @pytest.fixture
    def chunker(self):
        """Create CodeChunking instance."""
        try:
            from agno.knowledge.chunking.code import CodeChunking

            return CodeChunking(chunk_size=100)
        except ImportError:
            pytest.skip("chonkie[code] not installed")

    @pytest.fixture
    def code_document_with_id(self):
        """Code document with explicit ID."""
        return Document(
            id="code123",
            name="test.py",
            content='def hello():\n    print("Hello")\n\ndef world():\n    print("World")',
            meta_data={},
        )

    @pytest.fixture
    def code_document_with_name_only(self):
        """Code document with name but no ID."""
        return Document(
            id=None,
            name="my_script.py",
            content='def hello():\n    print("Hello")\n\ndef world():\n    print("World")',
            meta_data={},
        )

    @pytest.fixture
    def code_document_without_identifiers(self):
        """Code document with neither id nor name."""
        return Document(
            id=None,
            name=None,
            content='def hello():\n    print("Hello")\n\ndef world():\n    print("World")',
            meta_data={},
        )

    def test_uses_document_id(self, chunker, code_document_with_id):
        """Should use document.id for chunk IDs when available."""
        chunks = chunker.chunk(code_document_with_id)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id.startswith("code123_")

    def test_falls_back_to_document_name(self, chunker, code_document_with_name_only):
        """Should fall back to document.name when document.id is None."""
        chunks = chunker.chunk(code_document_with_name_only)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), "All chunks should have non-None IDs"
        assert chunks[0].id.startswith("my_script.py_")

    def test_falls_back_to_content_hash(self, chunker, code_document_without_identifiers):
        """Should fall back to content hash when both id and name are None.

        This is the critical test for Bug C9.
        Before fix: chunks had id=None
        After fix: chunks have id=chunk_{hash}_{number}
        """
        chunks = chunker.chunk(code_document_without_identifiers)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), (
            "CodeChunking should generate hash-based IDs for documents without id/name. "
            "Bug C9: CodeChunking was returning None IDs."
        )
        assert chunks[0].id.startswith("chunk_"), f"Expected hash-based ID, got: {chunks[0].id}"


# =============================================================================
# MarkdownChunking Tests
# =============================================================================


class TestMarkdownChunkingIdFallback:
    """Test MarkdownChunking ID generation fallback.

    MarkdownChunking was generating None chunk IDs for documents without id/name.
    """

    @pytest.fixture
    def chunker(self):
        """Create MarkdownChunking instance."""
        try:
            from agno.knowledge.chunking.markdown import MarkdownChunking

            return MarkdownChunking(chunk_size=100)
        except ImportError:
            pytest.skip("unstructured not installed")

    @pytest.fixture
    def md_document_with_id(self):
        """Markdown document with explicit ID."""
        return Document(
            id="md123",
            name="test.md",
            content="# Title\n\nParagraph one.\n\n## Section\n\nParagraph two.",
            meta_data={},
        )

    @pytest.fixture
    def md_document_with_name_only(self):
        """Markdown document with name but no ID."""
        return Document(
            id=None,
            name="readme.md",
            content="# Title\n\nParagraph one.\n\n## Section\n\nParagraph two.",
            meta_data={},
        )

    @pytest.fixture
    def md_document_without_identifiers(self):
        """Markdown document with neither id nor name."""
        return Document(
            id=None,
            name=None,
            content="# Title\n\nParagraph one.\n\n## Section\n\nParagraph two.",
            meta_data={},
        )

    def test_uses_document_id(self, chunker, md_document_with_id):
        """Should use document.id for chunk IDs when available."""
        chunks = chunker.chunk(md_document_with_id)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id.startswith("md123_")

    def test_falls_back_to_document_name(self, chunker, md_document_with_name_only):
        """Should fall back to document.name when document.id is None."""
        chunks = chunker.chunk(md_document_with_name_only)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), "All chunks should have non-None IDs"
        assert chunks[0].id.startswith("readme.md_")

    def test_falls_back_to_content_hash(self, chunker, md_document_without_identifiers):
        """Should fall back to content hash when both id and name are None.

        Before fix: chunks had id=None
        After fix: chunks have id=chunk_{hash}_{number}
        """
        chunks = chunker.chunk(md_document_without_identifiers)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), (
            "MarkdownChunking should generate hash-based IDs for documents without id/name."
        )
        assert chunks[0].id.startswith("chunk_"), f"Expected hash-based ID, got: {chunks[0].id}"


# =============================================================================
# Cross-Strategy Consistency Tests
# =============================================================================


class TestAllChunkersConsistentIdGeneration:
    """Verify all chunking strategies generate consistent ID patterns."""

    def test_all_chunkers_never_return_none_ids(self):
        """ALL chunking strategies should generate non-None IDs for any document."""
        from agno.knowledge.chunking.document import DocumentChunking
        from agno.knowledge.chunking.fixed import FixedSizeChunking
        from agno.knowledge.chunking.recursive import RecursiveChunking

        # Document with no identifiers - the edge case
        doc = Document(
            id=None,
            name=None,
            content="A" * 10000,  # Long enough to create multiple chunks
            meta_data={},
        )

        # Test built-in chunkers (no optional dependencies)
        chunkers = [
            ("DocumentChunking", DocumentChunking(chunk_size=2000)),
            ("FixedSizeChunking", FixedSizeChunking(chunk_size=2000)),
            ("RecursiveChunking", RecursiveChunking(chunk_size=2000)),
        ]

        for name, chunker in chunkers:
            chunks = chunker.chunk(doc)
            none_ids = [i for i, c in enumerate(chunks) if c.id is None]
            assert not none_ids, (
                f"{name} produced chunks with None IDs at indices {none_ids}. "
                "All chunkers should generate hash-based IDs for documents without id/name."
            )

    def test_hash_based_ids_are_deterministic(self):
        """Hash-based IDs should be deterministic - same content = same ID."""
        from agno.knowledge.chunking.document import DocumentChunking

        content = "This is test content for deterministic ID generation."
        doc1 = Document(id=None, name=None, content=content, meta_data={})
        doc2 = Document(id=None, name=None, content=content, meta_data={})

        chunker = DocumentChunking(chunk_size=100)

        chunks1 = chunker.chunk(doc1)
        chunks2 = chunker.chunk(doc2)

        assert chunks1[0].id == chunks2[0].id, "Same content should produce same chunk ID"
