"""Tests that Reader propagates chunk_size to its chunking_strategy."""

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.text_reader import TextReader


class DummyReader(Reader):
    """Minimal Reader subclass for testing."""

    def read(self, obj, name=None, password=None):
        return [Document(content=str(obj))]


class TestReaderChunkSizePropagation:
    """Verify that chunk_size is propagated to the chunking_strategy."""

    def test_chunk_size_propagated_to_fixed_size_chunking(self):
        reader = DummyReader(chunk_size=200, chunking_strategy=FixedSizeChunking())
        assert reader.chunking_strategy.chunk_size == 200
        assert reader.chunk_size == 200

    def test_chunk_size_propagated_to_document_chunking(self):
        reader = DummyReader(chunk_size=300, chunking_strategy=DocumentChunking())
        assert reader.chunking_strategy.chunk_size == 300

    def test_chunk_size_propagated_to_recursive_chunking(self):
        reader = DummyReader(chunk_size=400, chunking_strategy=RecursiveChunking())
        assert reader.chunking_strategy.chunk_size == 400

    def test_none_chunking_strategy_no_error(self):
        reader = DummyReader(chunk_size=100, chunking_strategy=None)
        assert reader.chunking_strategy is None

    def test_default_chunk_size_unchanged(self):
        reader = DummyReader(chunking_strategy=FixedSizeChunking())
        assert reader.chunking_strategy.chunk_size == 5000
        assert reader.chunk_size == 5000

    def test_custom_chunk_size_used_in_chunking(self):
        """Verify the propagated chunk_size actually affects chunking behavior."""
        chunk_size = 50
        reader = DummyReader(chunk_size=chunk_size, chunking_strategy=FixedSizeChunking())
        long_text = "a" * 200
        documents = reader.read(long_text)
        chunked = reader.chunk_document(documents[0])
        for doc in chunked:
            assert len(doc.content) <= chunk_size

    def test_text_reader_with_custom_chunk_size(self):
        """Test a real Reader subclass with custom chunk_size."""
        reader = TextReader(chunk_size=100)
        # TextReader defaults to FixedSizeChunking() - chunk_size should be propagated
        assert reader.chunking_strategy.chunk_size == 100
