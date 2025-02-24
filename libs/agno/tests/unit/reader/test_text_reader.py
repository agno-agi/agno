from io import BytesIO
from pathlib import Path

import pytest

from agno.document.base import Document
from agno.document.reader.text_reader import TextReader


@pytest.fixture
def test_read_text_file_path(tmp_path):
    # Create a temporary text file
    text_path = tmp_path / "test.txt"
    test_data = "Hello, world!"
    text_path.write_text(test_data)

    reader = TextReader()
    documents = reader.read(text_path)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == test_data


def test_read_text_bytesio():
    # Create a BytesIO object with text data
    test_data = "Hello, world!"
    text_bytes = BytesIO(test_data.encode())
    text_bytes.name = "test.txt"

    reader = TextReader()
    documents = reader.read(text_bytes)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == test_data


def test_chunking():
    # Test document chunking functionality
    test_data = "Hello, world!"
    text_bytes = BytesIO(test_data.encode())
    text_bytes.name = "test.txt"

    reader = TextReader()
    reader.chunk = True
    # Mock the chunk_document method
    reader.chunk_document = lambda doc: [
        Document(name=f"{doc.name}_chunk_{i}", id=f"{doc.id}_chunk_{i}", content=f"chunk_{i}", meta_data={"chunk": i})
        for i in range(2)
    ]

    documents = reader.read(text_bytes)

    assert len(documents) == 2
    assert all(doc.name.startswith("test_chunk_") for doc in documents)
    assert all(doc.id.startswith("test_chunk_") for doc in documents)
    assert all("chunk" in doc.meta_data for doc in documents)


def test_file_not_found():
    reader = TextReader()
    documents = reader.read(Path("nonexistent.txt"))
    assert len(documents) == 0


def test_unsupported_file_type():
    reader = TextReader()
    documents = reader.read("not_a_path_or_bytesio")
    assert len(documents) == 0


def test_empty_text_file(tmp_path):
    # Test handling of empty text file
    text_path = tmp_path / "empty.txt"
    text_path.write_text("")

    reader = TextReader()
    documents = reader.read(text_path)

    # No chunks can be extracted from an empty file
    assert len(documents) == 0


def test_unicode_content(tmp_path):
    # Test handling of Unicode content
    test_data = "Hello, 世界!"
    text_path = tmp_path / "unicode.txt"
    text_path.write_text(test_data)

    reader = TextReader()
    documents = reader.read(text_path)

    assert len(documents) == 1
    assert documents[0].content == test_data


def test_large_text_file(tmp_path):
    # Test handling of large text files
    test_data = "Hello, world!\n" * 1000
    text_path = tmp_path / "large.txt"
    text_path.write_text(test_data)

    reader = TextReader()
    documents = reader.read(text_path)

    # 3 chunks should be created
    assert len(documents) == 3
    assert documents[0].name == "large"


def test_invalid_encoding(tmp_path):
    # Test handling of invalid encoding
    text_path = tmp_path / "invalid.txt"
    try:
        with open(text_path, "wb") as f:
            f.write(b"\xff\xfe\x00\x00")  # Invalid UTF-8

        reader = TextReader()
        documents = reader.read(text_path)
        assert len(documents) == 0
    finally:
        # Clean up the file
        if text_path.exists():
            text_path.unlink()


def test_cp950_encoding(tmp_path):
    # Test handling of CP-950 (Traditional Chinese) encoded file
    test_data = "中文測試"  # Chinese test text
    text_path = tmp_path / "cp950.txt"
    try:
        with open(text_path, "w", encoding="cp950") as f:
            f.write(test_data)

        reader = TextReader()
        documents = reader.read(text_path)

        assert len(documents) == 0  # Currently returns 0 as TextReader only supports UTF-8
    finally:
        # Clean up the file
        if text_path.exists():
            text_path.unlink()
