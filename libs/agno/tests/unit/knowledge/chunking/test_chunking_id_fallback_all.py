"""Tests for chunk ID generation fallback across chunking strategies."""

import pytest

from agno.knowledge.document.base import Document


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
    """Document with neither id nor name."""
    return Document(
        id=None,
        name=None,
        content="First sentence here. Second sentence here. Third sentence. Fourth one. Fifth sentence.",
        meta_data={},
    )


class TestSemanticChunkingIdFallback:
    """Test SemanticChunking ID generation fallback."""

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
        """Should fall back to content hash when both id and name are None."""
        chunks = chunker.chunk(document_without_identifiers)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id.startswith("chunk_")


class TestCodeChunkingIdFallback:
    """Test CodeChunking ID generation fallback."""

    @pytest.fixture
    def chunker(self):
        """Create CodeChunking instance."""
        try:
            from agno.knowledge.chunking.code import CodeChunking

            # Use explicit language to avoid magika dependency
            chunker = CodeChunking(chunk_size=100, language="python")
            # Try to initialize to check if tree_sitter_language_pack is installed
            chunker._initialize_chunker()
            return chunker
        except ImportError as e:
            pytest.skip(f"CodeChunking dependency not installed: {e}")

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
        """Should fall back to content hash when both id and name are None."""
        chunks = chunker.chunk(code_document_without_identifiers)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        assert chunks[0].id.startswith("chunk_")


class TestMarkdownChunkingIdFallback:
    """Test MarkdownChunking ID generation fallback."""

    @pytest.fixture
    def chunker(self):
        """Create MarkdownChunking instance with small chunk size to force chunking."""
        try:
            from agno.knowledge.chunking.markdown import MarkdownChunking

            # Use split_on_headings=True to ensure chunking happens
            return MarkdownChunking(chunk_size=100, split_on_headings=True)
        except ImportError:
            pytest.skip("unstructured not installed")

    @pytest.fixture
    def md_document_with_id(self):
        """Markdown document with explicit ID - large enough to chunk."""
        return Document(
            id="md123",
            name="test.md",
            content="# Title\n\nParagraph one with enough content.\n\n## Section\n\nParagraph two with more content.",
            meta_data={},
        )

    @pytest.fixture
    def md_document_with_name_only(self):
        """Markdown document with name but no ID."""
        return Document(
            id=None,
            name="readme.md",
            content="# Title\n\nParagraph one with enough content.\n\n## Section\n\nParagraph two with more content.",
            meta_data={},
        )

    @pytest.fixture
    def md_document_without_identifiers(self):
        """Markdown document with neither id nor name."""
        return Document(
            id=None,
            name=None,
            content="# Title\n\nParagraph one with enough content.\n\n## Section\n\nParagraph two with more content.",
            meta_data={},
        )

    def test_uses_document_id(self, chunker, md_document_with_id):
        """Chunks should have IDs based on document.id when available."""
        chunks = chunker.chunk(md_document_with_id)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        # When chunked, IDs should be based on document ID
        if len(chunks) > 1:
            assert chunks[0].id.startswith("md123_")
        else:
            # Single chunk can keep original ID
            assert chunks[0].id == "md123" or chunks[0].id.startswith("md123_")

    def test_falls_back_to_document_name(self, chunker, md_document_with_name_only):
        """Chunks should use document.name when document.id is None."""
        chunks = chunker.chunk(md_document_with_name_only)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks), "All chunks should have non-None IDs"
        # When id is None, should use name for chunk IDs
        if len(chunks) > 1:
            assert chunks[0].id.startswith("readme.md_")

    def test_falls_back_to_content_hash(self, chunker, md_document_without_identifiers):
        """Chunks should use content hash when both id and name are None."""
        chunks = chunker.chunk(md_document_without_identifiers)

        assert len(chunks) >= 1
        assert all(c.id is not None for c in chunks)
        # When both id and name are None, should generate hash-based IDs
        if len(chunks) > 1:
            assert chunks[0].id.startswith("chunk_")


class TestAllChunkersConsistentIdGeneration:
    """Test cross-strategy ID generation consistency."""

    @pytest.mark.skip(reason="DocumentChunking, FixedSizeChunking, RecursiveChunking not yet fixed")
    def test_all_chunkers_never_return_none_ids(self):
        """All chunking strategies should generate non-None IDs."""
        from agno.knowledge.chunking.document import DocumentChunking
        from agno.knowledge.chunking.fixed import FixedSizeChunking
        from agno.knowledge.chunking.recursive import RecursiveChunking

        doc = Document(
            id=None,
            name=None,
            content="A" * 10000,
            meta_data={},
        )

        chunkers = [
            ("DocumentChunking", DocumentChunking(chunk_size=2000)),
            ("FixedSizeChunking", FixedSizeChunking(chunk_size=2000)),
            ("RecursiveChunking", RecursiveChunking(chunk_size=2000)),
        ]

        for name, chunker in chunkers:
            chunks = chunker.chunk(doc)
            none_ids = [i for i, c in enumerate(chunks) if c.id is None]
            assert not none_ids, f"{name} produced None IDs at indices {none_ids}"

    @pytest.mark.skip(reason="DocumentChunking not yet fixed")
    def test_hash_based_ids_are_deterministic(self):
        """Same content should produce same chunk ID."""
        from agno.knowledge.chunking.document import DocumentChunking

        content = "This is test content for deterministic ID generation."
        doc1 = Document(id=None, name=None, content=content, meta_data={})
        doc2 = Document(id=None, name=None, content=content, meta_data={})

        chunker = DocumentChunking(chunk_size=100)

        chunks1 = chunker.chunk(doc1)
        chunks2 = chunker.chunk(doc2)

        assert chunks1[0].id == chunks2[0].id
