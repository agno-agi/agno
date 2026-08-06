"""Tests that URL/topic readers honor their own ``self.chunk`` flag"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Content long enough that fixed-size chunking splits it into several chunks.
LONG_TEXT = "word " * 2000


def test_arxiv_reader_chunks_when_chunk_true():
    """chunk=True -> ArxivReader chunks each summary into multiple documents."""
    pytest.importorskip("arxiv")
    from agno.knowledge.reader.arxiv_reader import ArxivReader

    result = SimpleNamespace(
        title="A Paper",
        summary=LONG_TEXT,
        pdf_url="https://arxiv.org/pdf/1234.5678",
        links=[SimpleNamespace(href="https://arxiv.org/abs/1234.5678")],
    )
    reader = ArxivReader(chunk=True)
    with patch.object(reader, "get_client") as get_client:
        get_client.return_value.results.return_value = [result]
        docs = reader.read("quantum")

    assert len(docs) > 1


def test_arxiv_reader_keeps_whole_document_when_chunk_false():
    """chunk=False -> ArxivReader returns each summary as a single whole document."""
    pytest.importorskip("arxiv")
    from agno.knowledge.reader.arxiv_reader import ArxivReader

    result = SimpleNamespace(
        title="A Paper",
        summary=LONG_TEXT,
        pdf_url="https://arxiv.org/pdf/1234.5678",
        links=[SimpleNamespace(href="https://arxiv.org/abs/1234.5678")],
    )
    reader = ArxivReader(chunk=False)
    with patch.object(reader, "get_client") as get_client:
        get_client.return_value.results.return_value = [result]
        docs = reader.read("quantum")

    assert len(docs) == 1


def test_wikipedia_reader_chunks_when_chunk_true():
    """chunk=True -> WikipediaReader chunks the summary into multiple documents."""
    pytest.importorskip("wikipedia")
    from agno.knowledge.reader.wikipedia_reader import WikipediaReader

    reader = WikipediaReader(chunk=True)
    with patch("agno.knowledge.reader.wikipedia_reader.wikipedia") as wiki:
        wiki.summary.return_value = LONG_TEXT
        docs = reader.read("Python")

    assert len(docs) > 1


def test_wikipedia_reader_keeps_whole_document_when_chunk_false():
    """chunk=False -> WikipediaReader returns the summary as a single whole document."""
    pytest.importorskip("wikipedia")
    from agno.knowledge.reader.wikipedia_reader import WikipediaReader

    reader = WikipediaReader(chunk=False)
    with patch("agno.knowledge.reader.wikipedia_reader.wikipedia") as wiki:
        wiki.summary.return_value = LONG_TEXT
        docs = reader.read("Python")

    assert len(docs) == 1


@pytest.mark.asyncio
async def test_wikipedia_reader_async_respects_chunk_false():
    """Async path: chunk=False -> WikipediaReader returns a single whole document."""
    pytest.importorskip("wikipedia")
    from agno.knowledge.reader.wikipedia_reader import WikipediaReader

    reader = WikipediaReader(chunk=False)
    with patch("agno.knowledge.reader.wikipedia_reader.wikipedia") as wiki:
        wiki.summary.return_value = LONG_TEXT
        docs = await reader.async_read("Python")

    assert len(docs) == 1


def test_s3_reader_propagates_chunk_flag_to_inner_reader():
    """S3Reader must forward chunk/chunk_size/chunking_strategy to its inner reader."""
    pytest.importorskip("agno.knowledge.reader.s3_reader", exc_type=ImportError)

    from agno.knowledge.chunking.fixed import FixedSizeChunking
    from agno.knowledge.reader.s3_reader import S3Reader
    from agno.knowledge.reader.text_reader import TextReader

    strategy = FixedSizeChunking(chunk_size=123)
    reader = S3Reader(chunk=False, chunk_size=123, chunking_strategy=strategy)

    # The inner reader must inherit the S3Reader's chunking configuration; without
    # this it would default to chunk=True and ignore S3Reader(chunk=False).
    text_reader = reader._inner_reader(TextReader)
    assert text_reader.chunk is False
    assert text_reader.chunk_size == 123
    assert text_reader.chunking_strategy is strategy
