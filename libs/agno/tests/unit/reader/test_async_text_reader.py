import asyncio
from io import BytesIO
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from agno.document.base import Document
from agno.document.reader.text_reader import TextReader


@pytest.mark.asyncio
async def test_async_read_text_file_path(tmp_path):
    # Create a temporary text file
    text_path = tmp_path / "test.txt"
    test_data = "Hello, world!"
    text_path.write_text(test_data)

    reader = TextReader()
    documents = await reader.async_read(text_path)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == test_data


@pytest.mark.asyncio
async def test_async_read_text_bytesio():
    test_data = "Hello, world!"
    text_bytes = BytesIO(test_data.encode())
    text_bytes.name = "test.txt"

    reader = TextReader()
    documents = await reader.async_read(text_bytes)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == test_data


@pytest.mark.asyncio
async def test_async_chunking():
    test_data = "Hello, world!"
    text_bytes = BytesIO(test_data.encode())
    text_bytes.name = "test.txt"

    reader = TextReader()
    reader.chunk = True
    reader.chunk_document = lambda doc: [
        Document(name=f"{doc.name}_chunk_{i}", id=f"{doc.id}_chunk_{i}", content=f"chunk_{i}", meta_data={"chunk": i})
        for i in range(2)
    ]

    documents = await reader.async_read(text_bytes)

    assert len(documents) == 2
    assert all(doc.name.startswith("test_chunk_") for doc in documents)
    assert all(doc.id.startswith("test_chunk_") for doc in documents)
    assert all("chunk" in doc.meta_data for doc in documents)


@pytest.mark.asyncio
async def test_async_file_not_found():
    reader = TextReader()
    documents = await reader.async_read(Path("nonexistent.txt"))
    assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_unsupported_file_type():
    reader = TextReader()
    documents = await reader.async_read("not_a_path_or_bytesio")
    assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_empty_text_file(tmp_path):
    text_path = tmp_path / "empty.txt"
    text_path.write_text("")

    reader = TextReader()
    documents = await reader.async_read(text_path)

    assert len(documents) == 1
    assert documents[0].content == ""


@pytest.mark.asyncio
async def test_async_unicode_content(tmp_path):
    test_data = "Hello, 世界!"
    text_path = tmp_path / "unicode.txt"
    text_path.write_text(test_data)

    reader = TextReader()
    documents = await reader.async_read(text_path)

    assert len(documents) == 1
    assert documents[0].content == test_data


@pytest.mark.asyncio
async def test_async_large_text_file(tmp_path):
    test_data = "Hello, world!\n" * 1000
    text_path = tmp_path / "large.txt"
    text_path.write_text(test_data)

    reader = TextReader()
    reader.chunk = True
    documents = await reader.async_read(text_path)

    assert len(documents) > 0
    assert all(doc.name == "large" for doc in documents)


@pytest.mark.asyncio
async def test_async_with_aiofiles(tmp_path):
    test_data = "Hello, world!"
    text_path = tmp_path / "test.txt"
    text_path.write_text(test_data)

    with patch("aiofiles.open") as mock_aiofiles:
        # Mock the async context manager
        mock_aiofiles.return_value.__aenter__.return_value.read.return_value = test_data

        reader = TextReader()
        documents = await reader.async_read(text_path)

        assert len(documents) == 1
        assert documents[0].content == test_data
        mock_aiofiles.assert_called_once()


@pytest.mark.asyncio
async def test_async_without_aiofiles(tmp_path):
    test_data = "Hello, world!"
    text_path = tmp_path / "test.txt"
    text_path.write_text(test_data)

    with patch("agno.document.reader.text_reader.aiofiles", create=True) as mock_aiofiles:
        mock_aiofiles.open.side_effect = ImportError

        reader = TextReader()
        documents = await reader.async_read(text_path)

        assert len(documents) == 1
        assert documents[0].content == test_data


@pytest.mark.asyncio
async def test_async_invalid_encoding(tmp_path):
    text_path = tmp_path / "invalid.txt"
    try:
        with open(text_path, "wb") as f:
            f.write(b"\xff\xfe\x00\x00")  # Invalid UTF-8

        reader = TextReader()
        documents = await reader.async_read(text_path)
        assert len(documents) == 0
    finally:
        if text_path.exists():
            text_path.unlink()


@pytest.mark.asyncio
async def test_async_parallel_chunking():
    test_data = "Hello, world!"
    text_bytes = BytesIO(test_data.encode())
    text_bytes.name = "test.txt"

    reader = TextReader()
    reader.chunk = True

    # Mock chunking to return multiple documents
    reader.chunk_document = lambda doc: [
        Document(name=f"{doc.name}_chunk_{i}", id=f"{doc.id}_chunk_{i}", content=f"chunk_{i}", meta_data={"chunk": i})
        for i in range(2)
    ]

    # Create a mock async chunk processor
    async def mock_async_chunk_processor(document: Document) -> List[Document]:
        await asyncio.sleep(0.1)  # Simulate async work
        return reader.chunk_document(document)

    # Save original and replace with mock
    original_processor = reader._async_chunk_document
    reader._async_chunk_document = mock_async_chunk_processor

    try:
        documents = await reader.async_read(text_bytes)
        assert len(documents) == 2  # Should return 2 chunks
        assert all(doc.name.startswith("test_chunk_") for doc in documents)
        assert all(doc.id.startswith("test_chunk_") for doc in documents)
        assert all("chunk" in doc.meta_data for doc in documents)
    finally:
        # Restore original processor
        reader._async_chunk_document = original_processor
