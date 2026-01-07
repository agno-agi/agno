"""Tests for Knowledge.get_readers() method and ReaderFactory functionality."""

import pytest

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.utils import get_all_readers_info, get_reader_info
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Minimal VectorDb stub for testing."""

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents, filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents, filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents, filters=None) -> None:
        pass

    def search(self, query: str, limit: int = 5, filters=None):
        return []

    async def async_search(self, query: str, limit: int = 5, filters=None):
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def get_supported_search_types(self):
        return ["vector"]


class CustomReader(Reader):
    """Custom reader for testing."""

    def __init__(self, name: str = None, **kwargs):
        super().__init__(name=name, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(cls):
        from agno.knowledge.chunking.strategy import ChunkingStrategyType

        return [ChunkingStrategyType.FIXED_SIZE_CHUNKER]

    @classmethod
    def get_supported_content_types(cls):
        from agno.knowledge.types import ContentType

        return [ContentType.TXT]

    def read(self, obj, name=None):
        return []


def test_get_readers_with_none():
    """Test that get_readers() initializes empty dict when readers is None."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    knowledge.readers = None

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 0
    assert knowledge.readers == {}


def test_get_readers_with_empty_dict():
    """Test that get_readers() returns existing empty dict."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    knowledge.readers = {}

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 0
    assert result is knowledge.readers


def test_get_readers_with_existing_dict():
    """Test that get_readers() returns existing dict unchanged."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    reader1 = TextReader(name="reader1")
    reader2 = TextReader(name="reader2")
    knowledge.readers = {"reader1": reader1, "reader2": reader2}

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 2
    assert result["reader1"] is reader1
    assert result["reader2"] is reader2


def test_get_readers_converts_list_to_dict():
    """Test that get_readers() converts a list of readers to a dict."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    reader1 = TextReader(name="Custom Reader 1")
    reader2 = TextReader(name="Custom Reader 2")
    knowledge.readers = [reader1, reader2]

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 2
    # Check that readers are in the dict (keys are generated from names)
    assert all(isinstance(key, str) for key in result.keys())
    assert all(isinstance(val, Reader) for val in result.values())
    assert reader1 in result.values()
    assert reader2 in result.values()
    # Verify the conversion happened
    assert isinstance(knowledge.readers, dict)


def test_get_readers_handles_duplicate_keys():
    """Test that get_readers() handles duplicate keys by appending counter."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    # Create readers with same name to force duplicate keys
    reader1 = TextReader(name="custom_reader")
    reader2 = TextReader(name="custom_reader")
    reader3 = TextReader(name="custom_reader")
    knowledge.readers = [reader1, reader2, reader3]

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 3
    # Check that keys are unique
    keys = list(result.keys())
    assert len(keys) == len(set(keys))
    # Check that all readers are present
    assert reader1 in result.values()
    assert reader2 in result.values()
    assert reader3 in result.values()


def test_get_readers_skips_non_reader_objects():
    """Test that get_readers() skips non-Reader objects in the list."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    reader1 = TextReader(name="reader1")
    non_reader = "not a reader"
    reader2 = TextReader(name="reader2")
    knowledge.readers = [reader1, non_reader, reader2]

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 2
    assert reader1 in result.values()
    assert reader2 in result.values()
    assert non_reader not in result.values()


def test_get_readers_handles_empty_list():
    """Test that get_readers() handles empty list."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    knowledge.readers = []

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 0


def test_get_readers_resets_unexpected_types():
    """Test that get_readers() resets to empty dict for unexpected types."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    knowledge.readers = "not a list or dict"

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 0
    assert knowledge.readers == {}


def test_get_readers_with_readers_without_names():
    """Test that get_readers() generates keys from class name when reader has no name."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    reader1 = TextReader()  # No name
    reader2 = CustomReader()  # No name
    knowledge.readers = [reader1, reader2]

    result = knowledge.get_readers()

    assert isinstance(result, dict)
    assert len(result) == 2
    # Keys should be generated from class names
    keys = list(result.keys())
    assert any("textreader" in key.lower() for key in keys)
    assert any("customreader" in key.lower() for key in keys)


def test_get_readers_preserves_existing_dict_on_multiple_calls():
    """Test that get_readers() preserves the dict on multiple calls."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    reader1 = TextReader(name="reader1")
    reader2 = TextReader(name="reader2")
    knowledge.readers = {"reader1": reader1, "reader2": reader2}

    result1 = knowledge.get_readers()
    result2 = knowledge.get_readers()

    assert result1 is result2
    assert result1 is knowledge.readers
    assert len(result1) == 2


# ==========================================
# ReaderFactory Tests
# ==========================================


def test_reader_factory_metadata_exists():
    """Test that READER_METADATA contains all expected readers."""
    expected_readers = [
        "pdf",
        "csv",
        "docx",
        "pptx",
        "json",
        "markdown",
        "text",
        "website",
        "firecrawl",
        "tavily",
        "youtube",
        "arxiv",
        "wikipedia",
        "web_search",
    ]

    for reader_key in expected_readers:
        assert reader_key in ReaderFactory.READER_METADATA
        assert "name" in ReaderFactory.READER_METADATA[reader_key]
        assert "description" in ReaderFactory.READER_METADATA[reader_key]


def test_reader_factory_get_reader_class_returns_class():
    """Test that get_reader_class returns a class, not an instance."""
    reader_class = ReaderFactory.get_reader_class("text")

    # Should be a class, not an instance
    assert isinstance(reader_class, type)
    assert reader_class.__name__ == "TextReader"


def test_reader_factory_get_reader_class_unknown_raises():
    """Test that get_reader_class raises ValueError for unknown reader."""
    with pytest.raises(ValueError, match="Unknown reader"):
        ReaderFactory.get_reader_class("nonexistent_reader")


def test_reader_factory_get_reader_class_supports_class_methods():
    """Test that reader class from factory supports class methods without instantiation."""
    # Use text reader as it has no optional dependencies
    reader_class = ReaderFactory.get_reader_class("text")

    # Should be able to call class methods without creating an instance
    strategies = reader_class.get_supported_chunking_strategies()
    content_types = reader_class.get_supported_content_types()

    assert isinstance(strategies, list)
    assert len(strategies) > 0
    assert isinstance(content_types, list)
    assert len(content_types) > 0


def test_reader_factory_get_all_reader_keys():
    """Test that get_all_reader_keys returns all reader keys."""
    keys = ReaderFactory.get_all_reader_keys()

    assert isinstance(keys, list)
    assert len(keys) > 0
    assert "pdf" in keys
    assert "text" in keys
    assert "website" in keys


# ==========================================
# Reader Utils Tests
# ==========================================


def test_get_reader_info_returns_correct_structure():
    """Test that get_reader_info returns expected structure without instantiation."""
    info = get_reader_info("text")

    assert isinstance(info, dict)
    assert info["id"] == "text"
    assert "name" in info
    assert "description" in info
    assert "chunking_strategies" in info
    assert "content_types" in info
    assert isinstance(info["chunking_strategies"], list)
    assert isinstance(info["content_types"], list)


def test_get_reader_info_unknown_raises():
    """Test that get_reader_info raises ValueError for unknown reader."""
    with pytest.raises(ValueError, match="Unknown reader"):
        get_reader_info("nonexistent_reader")


def test_get_all_readers_info_returns_list():
    """Test that get_all_readers_info returns a list of reader info dicts."""
    readers_info = get_all_readers_info()

    assert isinstance(readers_info, list)
    assert len(readers_info) > 0
    # Each item should have expected keys
    for info in readers_info:
        assert "id" in info
        assert "name" in info
        assert "chunking_strategies" in info


def test_get_all_readers_info_custom_readers_first():
    """Test that custom readers appear before factory readers."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    custom_reader = CustomReader(name="My Custom Reader")
    knowledge.readers = {"my_custom": custom_reader}

    readers_info = get_all_readers_info(knowledge)

    # Custom reader should be first
    assert readers_info[0]["id"] == "my_custom"
    assert readers_info[0]["name"] == "My Custom Reader"


def test_get_all_readers_info_custom_reader_takes_precedence():
    """Test that custom readers with same ID as factory readers take precedence."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    # Create a custom reader with same key as a factory reader
    custom_pdf = CustomReader(name="My Custom PDF")
    knowledge.readers = {"pdf": custom_pdf}

    readers_info = get_all_readers_info(knowledge)

    # Find the pdf entry
    pdf_info = next((r for r in readers_info if r["id"] == "pdf"), None)
    assert pdf_info is not None
    # Should be our custom reader, not the factory one
    assert pdf_info["name"] == "My Custom PDF"
    # Should only have one pdf entry
    pdf_count = sum(1 for r in readers_info if r["id"] == "pdf")
    assert pdf_count == 1
