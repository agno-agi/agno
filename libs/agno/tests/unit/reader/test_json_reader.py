import json
from io import BytesIO
from pathlib import Path

import pytest

from agno.document.base import Document
from agno.document.reader.json_reader import JSONReader


@pytest.fixture
def test_read_json_file_path(tmp_path):
    # Create a temporary JSON file
    json_path = tmp_path / "test.json"
    test_data = {"key": "value"}
    json_path.write_text(json.dumps(test_data))

    reader = JSONReader()
    documents = reader.read(json_path)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert json.loads(documents[0].content) == test_data


def test_read_json_bytesio():
    # Create a BytesIO object with JSON data
    test_data = {"key": "value"}
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "test.json"

    reader = JSONReader()
    documents = reader.read(json_bytes)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert json.loads(documents[0].content) == test_data


def test_read_json_list():
    # Test reading a JSON file containing a list
    test_data = [{"key1": "value1"}, {"key2": "value2"}]
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "test.json"

    reader = JSONReader()
    documents = reader.read(json_bytes)

    assert len(documents) == 2
    assert all(doc.name == "test" for doc in documents)
    assert [json.loads(doc.content) for doc in documents] == test_data


def test_chunking():
    # Test document chunking functionality
    test_data = {"key": "value"}
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "test.json"

    reader = JSONReader()
    reader.chunk = True
    reader.chunk_document = lambda doc: [
        Document(name=f"{doc.name}_chunk_{i}", id=f"{doc.id}_chunk_{i}", content=f"chunk_{i}", meta_data={"chunk": i})
        for i in range(2)
    ]

    documents = reader.read(json_bytes)

    assert len(documents) == 2
    assert all(doc.name.startswith("test_chunk_") for doc in documents)
    assert all(doc.id.startswith("test_1_chunk_") for doc in documents)
    assert all("chunk" in doc.meta_data for doc in documents)


def test_file_not_found():
    reader = JSONReader()
    with pytest.raises(FileNotFoundError):
        reader.read(Path("nonexistent.json"))


def test_invalid_json():
    # Test handling of invalid JSON data
    invalid_json = BytesIO(b"{invalid_json")
    invalid_json.name = "invalid.json"

    reader = JSONReader()
    with pytest.raises(json.JSONDecodeError):
        reader.read(invalid_json)


def test_unsupported_file_type():
    reader = JSONReader()
    with pytest.raises(ValueError, match="Unsupported file type"):
        reader.read("not_a_path_or_bytesio")


def test_empty_json_file(tmp_path):
    # Test handling of empty JSON file
    json_path = tmp_path / "empty.json"
    json_path.write_text("")

    reader = JSONReader()
    with pytest.raises(json.JSONDecodeError):
        reader.read(json_path)


def test_empty_json_array(tmp_path):
    # Test handling of empty JSON array
    json_path = tmp_path / "empty_array.json"
    json_path.write_text("[]")

    reader = JSONReader()
    documents = reader.read(json_path)
    assert len(documents) == 0


def test_unicode_content(tmp_path):
    # Test handling of Unicode content
    test_data = {"key": "值"}
    json_path = tmp_path / "unicode.json"
    json_path.write_text(json.dumps(test_data))

    reader = JSONReader()
    documents = reader.read(json_path)

    assert len(documents) == 1
    assert json.loads(documents[0].content) == test_data


def test_nested_json():
    # Test handling of deeply nested JSON
    test_data = {"level1": {"level2": {"level3": "value"}}}
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "nested.json"

    reader = JSONReader()
    documents = reader.read(json_bytes)

    assert len(documents) == 1
    assert json.loads(documents[0].content) == test_data


def test_large_json():
    # Test handling of large JSON files
    test_data = [{"key": f"value_{i}"} for i in range(1000)]
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "large.json"

    reader = JSONReader()
    documents = reader.read(json_bytes)

    assert len(documents) == 1000
    assert all(doc.name == "large" for doc in documents)
    assert all(doc.id.startswith("large_") for doc in documents)


@pytest.mark.asyncio
async def test_async_read_json_file_path(tmp_path):
    # Create a temporary JSON file
    json_path = tmp_path / "test.json"
    test_data = {"key": "value"}
    json_path.write_text(json.dumps(test_data))

    reader = JSONReader()
    documents = await reader.async_read(json_path)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert json.loads(documents[0].content) == test_data


@pytest.mark.asyncio
async def test_async_read_json_bytesio():
    test_data = {"key": "value"}
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "test.json"

    reader = JSONReader()
    documents = await reader.async_read(json_bytes)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert json.loads(documents[0].content) == test_data


@pytest.mark.asyncio
async def test_async_read_json_list():
    test_data = [{"key1": "value1"}, {"key2": "value2"}]
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "test.json"

    reader = JSONReader()
    documents = await reader.async_read(json_bytes)

    assert len(documents) == 2
    assert all(doc.name == "test" for doc in documents)
    assert [json.loads(doc.content) for doc in documents] == test_data


@pytest.mark.asyncio
async def test_async_chunking():
    test_data = {"key": "value"}
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "test.json"

    reader = JSONReader()
    reader.chunk = True
    reader.chunk_document = lambda doc: [
        Document(name=f"{doc.name}_chunk_{i}", id=f"{doc.id}_chunk_{i}", content=f"chunk_{i}", meta_data={"chunk": i})
        for i in range(2)
    ]

    documents = await reader.async_read(json_bytes)

    assert len(documents) == 2
    assert all(doc.name.startswith("test_chunk_") for doc in documents)
    assert all(doc.id.startswith("test_1_chunk_") for doc in documents)
    assert all("chunk" in doc.meta_data for doc in documents)


@pytest.mark.asyncio
async def test_async_file_not_found():
    reader = JSONReader()
    with pytest.raises(FileNotFoundError):
        await reader.async_read(Path("nonexistent.json"))


@pytest.mark.asyncio
async def test_async_invalid_json():
    invalid_json = BytesIO(b"{invalid_json")
    invalid_json.name = "invalid.json"

    reader = JSONReader()
    with pytest.raises(json.JSONDecodeError):
        await reader.async_read(invalid_json)


@pytest.mark.asyncio
async def test_async_unsupported_file_type():
    reader = JSONReader()
    with pytest.raises(ValueError, match="Unsupported file type"):
        await reader.async_read("not_a_path_or_bytesio")


@pytest.mark.asyncio
async def test_async_unicode_content(tmp_path):
    test_data = {"key": "值"}
    json_path = tmp_path / "unicode.json"
    json_path.write_text(json.dumps(test_data))

    reader = JSONReader()
    documents = await reader.async_read(json_path)

    assert len(documents) == 1
    assert json.loads(documents[0].content) == test_data


@pytest.mark.asyncio
async def test_async_large_json():
    test_data = [{"key": f"value_{i}"} for i in range(1000)]
    json_bytes = BytesIO(json.dumps(test_data).encode())
    json_bytes.name = "large.json"

    reader = JSONReader()
    documents = await reader.async_read(json_bytes)

    assert len(documents) == 1000
    assert all(doc.name == "large" for doc in documents)
    assert all(doc.id.startswith("large_") for doc in documents)
