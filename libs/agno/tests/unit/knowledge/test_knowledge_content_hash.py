"""Tests for Knowledge._build_content_hash() method, verifying hash includes name and description."""

from agno.knowledge.content import Content
from agno.knowledge.knowledge import Knowledge
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


def test_url_hash_without_name_or_description():
    """Test that URL hash without name/description is backward compatible."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf")
    content2 = Content(url="https://example.com/doc.pdf")

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    assert hash1 == hash2
    assert isinstance(hash1, str)
    assert len(hash1) == 64  # SHA256 hex digest length


def test_url_hash_with_different_names():
    """Test that same URL with different names produces different hashes."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf", name="Document 1")
    content2 = Content(url="https://example.com/doc.pdf", name="Document 2")
    content3 = Content(url="https://example.com/doc.pdf")  # No name

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # All hashes should be different
    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3


def test_url_hash_with_different_descriptions():
    """Test that same URL with different descriptions produces different hashes."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf", description="First description")
    content2 = Content(url="https://example.com/doc.pdf", description="Second description")
    content3 = Content(url="https://example.com/doc.pdf")  # No description

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # All hashes should be different
    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3


def test_url_hash_with_name_and_description():
    """Test that URL hash includes both name and description."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf", name="Document 1", description="Description 1")
    content2 = Content(url="https://example.com/doc.pdf", name="Document 1", description="Description 2")
    content3 = Content(url="https://example.com/doc.pdf", name="Document 2", description="Description 1")
    content4 = Content(url="https://example.com/doc.pdf", name="Document 1", description="Description 1")

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)
    hash4 = knowledge._build_content_hash(content4)

    # Same name and description should produce same hash
    assert hash1 == hash4

    # Different name or description should produce different hashes
    assert hash1 != hash2  # Different description
    assert hash1 != hash3  # Different name


def test_path_hash_with_name_and_description():
    """Test that path hash includes both name and description."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(path="/path/to/file.pdf", name="File 1", description="Desc 1")
    content2 = Content(path="/path/to/file.pdf", name="File 1", description="Desc 2")
    content3 = Content(path="/path/to/file.pdf", name="File 2", description="Desc 1")
    content4 = Content(path="/path/to/file.pdf")  # No name or description

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)
    hash4 = knowledge._build_content_hash(content4)

    # Different combinations should produce different hashes
    assert hash1 != hash2
    assert hash1 != hash3
    assert hash1 != hash4
    assert hash2 != hash3
    assert hash2 != hash4
    assert hash3 != hash4


def test_path_hash_backward_compatibility():
    """Test that path hash without name/description is backward compatible."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(path="/path/to/file.pdf")
    content2 = Content(path="/path/to/file.pdf")

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    assert hash1 == hash2


def test_same_url_name_description_produces_same_hash():
    """Test that identical URL, name, and description produce the same hash."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf", name="Document", description="Description")
    content2 = Content(url="https://example.com/doc.pdf", name="Document", description="Description")

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    assert hash1 == hash2


def test_hash_order_matters():
    """Test that the order of name and description in hash is consistent."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    # Same URL, name, description should always produce same hash
    content = Content(url="https://example.com/doc.pdf", name="Document", description="Description")

    hash1 = knowledge._build_content_hash(content)
    hash2 = knowledge._build_content_hash(content)
    hash3 = knowledge._build_content_hash(content)

    # Should be deterministic
    assert hash1 == hash2 == hash3


def test_hash_with_only_name():
    """Test hash with URL and name but no description."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf", name="Document 1")
    content2 = Content(url="https://example.com/doc.pdf", name="Document 2")
    content3 = Content(url="https://example.com/doc.pdf")  # No name

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3


def test_hash_with_only_description():
    """Test hash with URL and description but no name."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com/doc.pdf", description="Description 1")
    content2 = Content(url="https://example.com/doc.pdf", description="Description 2")
    content3 = Content(url="https://example.com/doc.pdf")  # No description

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3
