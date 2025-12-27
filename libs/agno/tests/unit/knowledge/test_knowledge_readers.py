"""Tests for Knowledge.get_readers() method, specifically testing list to dict conversion."""

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.text_reader import TextReader
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
