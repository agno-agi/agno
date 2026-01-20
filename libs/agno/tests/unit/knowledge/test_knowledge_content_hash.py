"""Tests for Knowledge._build_content_hash() method, verifying hash includes name and description."""

from agno.knowledge.content import Content, FileData
from agno.knowledge.document.base import Document
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


def test_file_data_hash_with_filename():
    """Test that file_data hash uses filename when available."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content", filename="file1.pdf"))
    content2 = Content(file_data=FileData(content="test content", filename="file2.pdf"))
    content3 = Content(file_data=FileData(content="different content", filename="file1.pdf"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different filenames should produce different hashes
    assert hash1 != hash2
    # Same filename should produce same hash (even with different content)
    assert hash1 == hash3


def test_file_data_hash_with_type():
    """Test that file_data hash uses type when filename is not available."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content", type="application/pdf"))
    content2 = Content(file_data=FileData(content="test content", type="text/plain"))
    content3 = Content(file_data=FileData(content="different content", type="application/pdf"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different types should produce different hashes
    assert hash1 != hash2
    # Same type should produce same hash (even with different content)
    assert hash1 == hash3


def test_file_data_hash_with_size():
    """Test that file_data hash uses size when filename and type are not available."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content", size=1024))
    content2 = Content(file_data=FileData(content="test content", size=2048))
    content3 = Content(file_data=FileData(content="different content", size=1024))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different sizes should produce different hashes
    assert hash1 != hash2
    # Same size should produce same hash (even with different content)
    assert hash1 == hash3


def test_file_data_hash_with_content_fallback():
    """Test that file_data hash uses content hash when no filename/type/size/name/description."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content 1"))
    content2 = Content(file_data=FileData(content="test content 2"))
    content3 = Content(file_data=FileData(content="test content 1"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different content should produce different hashes
    assert hash1 != hash2
    # Same content should produce same hash
    assert hash1 == hash3


def test_file_data_hash_with_name_and_description():
    """Test that file_data hash includes both name/description and file_data fields."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(
        name="Document 1",
        description="Description 1",
        file_data=FileData(content="test content", filename="file1.pdf", type="application/pdf", size=1024),
    )
    content2 = Content(
        name="Document 1",
        description="Description 1",
        file_data=FileData(content="different content", filename="file1.pdf", type="application/pdf", size=1024),
    )
    content3 = Content(
        name="Document 1",
        description="Description 1",
        file_data=FileData(content="test content", filename="file2.pdf", type="application/pdf", size=1024),
    )
    content4 = Content(
        name="Document 2",
        description="Description 1",
        file_data=FileData(content="test content", filename="file1.pdf", type="application/pdf", size=1024),
    )

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)
    hash4 = knowledge._build_content_hash(content4)

    # Same name/description/filename should produce same hash (content difference ignored when filename present)
    assert hash1 == hash2
    # Different filename should produce different hash
    assert hash1 != hash3
    # Different name should produce different hash
    assert hash1 != hash4


def test_file_data_hash_priority_filename_over_type():
    """Test that filename takes priority over type."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test", filename="file.pdf", type="application/pdf"))
    content2 = Content(file_data=FileData(content="test", filename="file.pdf", type="text/plain"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    # Same filename should produce same hash regardless of type
    assert hash1 == hash2


def test_file_data_hash_priority_type_over_size():
    """Test that type takes priority over size."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test", type="application/pdf", size=1024))
    content2 = Content(file_data=FileData(content="test", type="application/pdf", size=2048))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    # Same type should produce same hash regardless of size
    assert hash1 == hash2


def test_file_data_hash_with_name_only():
    """Test file_data hash with name but no description."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(name="Document 1", file_data=FileData(content="test content", filename="file1.pdf"))
    content2 = Content(name="Document 2", file_data=FileData(content="test content", filename="file1.pdf"))
    content3 = Content(file_data=FileData(content="test content", filename="file1.pdf"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different names should produce different hashes
    assert hash1 != hash2
    # Name + filename should be different from just filename
    assert hash1 != hash3


def test_file_data_hash_with_description_only():
    """Test file_data hash with description but no name."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(description="Description 1", file_data=FileData(content="test content", filename="file1.pdf"))
    content2 = Content(description="Description 2", file_data=FileData(content="test content", filename="file1.pdf"))
    content3 = Content(file_data=FileData(content="test content", filename="file1.pdf"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different descriptions should produce different hashes
    assert hash1 != hash2
    # Description + filename should be different from just filename
    assert hash1 != hash3


def test_file_data_hash_bytes_content():
    """Test file_data hash with bytes content."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content=b"test content bytes"))
    content2 = Content(file_data=FileData(content=b"test content bytes"))
    content3 = Content(file_data=FileData(content=b"different bytes"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Same bytes content should produce same hash
    assert hash1 == hash2
    # Different bytes content should produce different hash
    assert hash1 != hash3


def test_file_data_hash_string_vs_bytes_same_content():
    """Test that string and bytes with same content produce different hashes (different types)."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content"))
    content2 = Content(file_data=FileData(content=b"test content"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    # String and bytes are different types, so they should produce different hashes
    assert hash1 != hash2


def test_file_data_hash_all_fields_present():
    """Test file_data hash when all fields are present."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(
        name="Doc 1",
        description="Desc 1",
        file_data=FileData(content="content", filename="file.pdf", type="application/pdf", size=1024),
    )
    content2 = Content(
        name="Doc 1",
        description="Desc 1",
        file_data=FileData(content="different", filename="file.pdf", type="application/pdf", size=1024),
    )
    content3 = Content(
        name="Doc 1",
        description="Desc 1",
        file_data=FileData(content="content", filename="other.pdf", type="application/pdf", size=1024),
    )

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Same name/description/filename should produce same hash (content/type/size differences ignored when filename present)
    assert hash1 == hash2
    # Different filename should produce different hash
    assert hash1 != hash3


def test_file_data_hash_empty_hash_parts_fallback():
    """Test that file_data with no name/description/fields uses content hash."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    # FileData with content but no filename, type, size, name, or description
    content1 = Content(file_data=FileData(content="content1"))
    content2 = Content(file_data=FileData(content="content2"))
    content3 = Content(file_data=FileData(content="content1"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different content should produce different hashes
    assert hash1 != hash2
    # Same content should produce same hash
    assert hash1 == hash3
    # Verify hash is valid SHA256
    assert isinstance(hash1, str)
    assert len(hash1) == 64


def test_document_content_hash_uses_document_url():
    """Documents from different URLs get unique content hashes."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content = Content(url="https://example.com")

    doc1 = Document(content="Page 1 content", meta_data={"url": "https://example.com/page1"})
    doc2 = Document(content="Page 2 content", meta_data={"url": "https://example.com/page2"})
    doc3 = Document(content="Page 3 content", meta_data={"url": "https://example.com/page3"})

    hash1 = knowledge._build_document_content_hash(doc1, content)
    hash2 = knowledge._build_document_content_hash(doc2, content)
    hash3 = knowledge._build_document_content_hash(doc3, content)

    # Different URLs should produce different hashes
    assert hash1 != hash2
    assert hash2 != hash3
    assert hash1 != hash3

    # Verify hashes are valid SHA256
    assert len(hash1) == 64
    assert len(hash2) == 64
    assert len(hash3) == 64


def test_document_content_hash_is_deterministic():
    """Same document URL produces same hash (deterministic)."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content = Content(url="https://example.com")

    doc1 = Document(content="Page 1 content", meta_data={"url": "https://example.com/page1"})
    doc2 = Document(content="Different content", meta_data={"url": "https://example.com/page1"})

    hash1 = knowledge._build_document_content_hash(doc1, content)
    hash2 = knowledge._build_document_content_hash(doc2, content)

    # Same URL should produce same hash regardless of content
    assert hash1 == hash2


def test_document_content_hash_includes_content_name():
    """Document hash includes content name for uniqueness."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com", name="Site A")
    content2 = Content(url="https://example.com", name="Site B")

    doc = Document(content="Page content", meta_data={"url": "https://example.com/page"})

    hash1 = knowledge._build_document_content_hash(doc, content1)
    hash2 = knowledge._build_document_content_hash(doc, content2)

    # Different content names should produce different hashes
    assert hash1 != hash2


def test_document_content_hash_includes_content_description():
    """Document hash includes content description for uniqueness."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(url="https://example.com", description="Description A")
    content2 = Content(url="https://example.com", description="Description B")

    doc = Document(content="Page content", meta_data={"url": "https://example.com/page"})

    hash1 = knowledge._build_document_content_hash(doc, content1)
    hash2 = knowledge._build_document_content_hash(doc, content2)

    # Different descriptions should produce different hashes
    assert hash1 != hash2


def test_document_content_hash_fallback_to_content_url():
    """Document without URL in meta_data falls back to content URL."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content = Content(url="https://example.com/fallback")

    doc = Document(content="Page content", meta_data={})

    hash1 = knowledge._build_document_content_hash(doc, content)

    # Should produce a valid hash using content URL
    assert len(hash1) == 64


def test_document_content_hash_fallback_to_content_hash():
    """Document without any URL falls back to document content hash."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content = Content()  # No URL or path

    doc1 = Document(content="Page 1 content", meta_data={})
    doc2 = Document(content="Page 2 content", meta_data={})
    doc3 = Document(content="Page 1 content", meta_data={})

    hash1 = knowledge._build_document_content_hash(doc1, content)
    hash2 = knowledge._build_document_content_hash(doc2, content)
    hash3 = knowledge._build_document_content_hash(doc3, content)

    # Different content should produce different hashes
    assert hash1 != hash2
    # Same content should produce same hash
    assert hash1 == hash3
