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
    """Test that file_data hash incorporates both filename and content bytes."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content", filename="file1.pdf"))
    content2 = Content(file_data=FileData(content="test content", filename="file2.pdf"))
    content3 = Content(file_data=FileData(content="different content", filename="file1.pdf"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different filenames (same content) → different hashes
    assert hash1 != hash2
    # Different content (same filename) → different hashes (content bytes are primary)
    assert hash1 != hash3


def test_file_data_hash_with_type():
    """Test that file_data hash incorporates both type and content bytes."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content", type="application/pdf"))
    content2 = Content(file_data=FileData(content="test content", type="text/plain"))
    content3 = Content(file_data=FileData(content="different content", type="application/pdf"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different types (same content) → different hashes
    assert hash1 != hash2
    # Different content (same type) → different hashes (content bytes are primary)
    assert hash1 != hash3


def test_file_data_hash_with_size():
    """Test that file_data hash incorporates both size and content bytes."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test content", size=1024))
    content2 = Content(file_data=FileData(content="test content", size=2048))
    content3 = Content(file_data=FileData(content="different content", size=1024))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)
    hash3 = knowledge._build_content_hash(content3)

    # Different sizes (same content) → different hashes
    assert hash1 != hash2
    # Different content (same size) → different hashes (content bytes are primary)
    assert hash1 != hash3


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
    """Test that file_data hash includes name, description, filename, AND content bytes."""
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

    # Different content (same name/description/filename) → different hashes (content bytes are primary)
    assert hash1 != hash2
    # Different filename (same content/name/description) → different hashes
    assert hash1 != hash3
    # Different name (same content/description/filename) → different hashes
    assert hash1 != hash4


def test_file_data_hash_all_metadata_same_produces_same_hash():
    """Identical content AND identical metadata must produce the same hash (dedup)."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(
        name="Document 1",
        description="Description 1",
        file_data=FileData(content="test content", filename="file1.pdf", type="application/pdf", size=1024),
    )
    content2 = Content(
        name="Document 1",
        description="Description 1",
        file_data=FileData(content="test content", filename="file1.pdf", type="application/pdf", size=1024),
    )
    assert knowledge._build_content_hash(content1) == knowledge._build_content_hash(content2)


def test_file_data_hash_filename_and_type_both_discriminate():
    """With the fix, filename AND type are both part of the hash (non-exclusive).
    Same content + same filename but different type → different hashes.
    """
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test", filename="file.pdf", type="application/pdf"))
    content2 = Content(file_data=FileData(content="test", filename="file.pdf", type="text/plain"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    # Same content + same filename but different type → different hashes
    assert hash1 != hash2


def test_file_data_hash_type_and_size_both_discriminate():
    """With the fix, type AND size are both part of the hash (non-exclusive).
    Same content + same type but different size → different hashes.
    """
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="test", type="application/pdf", size=1024))
    content2 = Content(file_data=FileData(content="test", type="application/pdf", size=2048))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    # Same content + same type but different size → different hashes
    assert hash1 != hash2


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
    """Test file_data hash when all fields are present — content bytes are primary."""
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

    # Different content (same filename/name/description) → different hashes (content bytes are primary)
    assert hash1 != hash2
    # Different filename (same content/name/description) → different hashes
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


def test_github_same_path_different_repos_produces_different_hashes():
    """Two GitHub uploads with the same file path but different repos must not collide."""
    from agno.knowledge.remote_content.github import GitHubConfig

    knowledge = Knowledge(vector_db=MockVectorDb())
    cfg = GitHubConfig(id="gh", name="GH", branch="main")

    content_a = Content(name="README.md", remote_content=cfg.file("README.md", repo="orgA/x"))
    content_b = Content(name="README.md", remote_content=cfg.file("README.md", repo="orgB/y"))

    assert knowledge._build_content_hash(content_a) != knowledge._build_content_hash(content_b)


def test_github_same_repo_same_path_produces_same_hash():
    """Deduplication still works when the full source identity matches."""
    from agno.knowledge.remote_content.github import GitHubConfig

    knowledge = Knowledge(vector_db=MockVectorDb())
    cfg = GitHubConfig(id="gh", name="GH", branch="main")

    content_a = Content(name="README.md", remote_content=cfg.file("README.md", repo="orgA/x"))
    content_b = Content(name="README.md", remote_content=cfg.file("README.md", repo="orgA/x"))

    assert knowledge._build_content_hash(content_a) == knowledge._build_content_hash(content_b)


def test_github_different_branches_produces_different_hashes():
    """A branch override is part of the source identity and must affect the hash."""
    from agno.knowledge.remote_content.github import GitHubConfig

    knowledge = Knowledge(vector_db=MockVectorDb())
    cfg = GitHubConfig(id="gh", name="GH", repo="orgA/x")

    content_a = Content(name="README.md", remote_content=cfg.file("README.md", branch="main"))
    content_b = Content(name="README.md", remote_content=cfg.file("README.md", branch="dev"))

    assert knowledge._build_content_hash(content_a) != knowledge._build_content_hash(content_b)


def test_s3_same_key_different_buckets_produces_different_hashes():
    """Same S3 key pulled from two different buckets must not collide."""
    from agno.knowledge.remote_content.remote_content import S3Content

    knowledge = Knowledge(vector_db=MockVectorDb())

    content_a = Content(name="report.pdf", remote_content=S3Content(bucket_name="bucket-a", key="report.pdf"))
    content_b = Content(name="report.pdf", remote_content=S3Content(bucket_name="bucket-b", key="report.pdf"))

    assert knowledge._build_content_hash(content_a) != knowledge._build_content_hash(content_b)


def test_gcs_same_blob_different_buckets_produces_different_hashes():
    """Same GCS blob name pulled from two different buckets must not collide."""
    from agno.knowledge.remote_content.remote_content import GCSContent

    knowledge = Knowledge(vector_db=MockVectorDb())

    content_a = Content(name="data.csv", remote_content=GCSContent(bucket_name="bucket-a", blob_name="data.csv"))
    content_b = Content(name="data.csv", remote_content=GCSContent(bucket_name="bucket-b", blob_name="data.csv"))

    assert knowledge._build_content_hash(content_a) != knowledge._build_content_hash(content_b)


def test_azure_blob_same_blob_different_configs_produces_different_hashes():
    """Same Azure blob name from two different configs (different containers) must not collide."""
    from agno.knowledge.remote_content.remote_content import AzureBlobContent

    knowledge = Knowledge(vector_db=MockVectorDb())

    content_a = Content(name="file.txt", remote_content=AzureBlobContent(config_id="az-a", blob_name="file.txt"))
    content_b = Content(name="file.txt", remote_content=AzureBlobContent(config_id="az-b", blob_name="file.txt"))

    assert knowledge._build_content_hash(content_a) != knowledge._build_content_hash(content_b)


def test_sharepoint_same_path_different_sites_produces_different_hashes():
    """Same SharePoint file path from two different sites must not collide."""
    from agno.knowledge.remote_content.remote_content import SharePointContent

    knowledge = Knowledge(vector_db=MockVectorDb())

    content_a = Content(
        name="spec.docx",
        remote_content=SharePointContent(config_id="sp", site_path="/sites/a", file_path="spec.docx"),
    )
    content_b = Content(
        name="spec.docx",
        remote_content=SharePointContent(config_id="sp", site_path="/sites/b", file_path="spec.docx"),
    )

    assert knowledge._build_content_hash(content_a) != knowledge._build_content_hash(content_b)


def test_non_remote_content_hash_unchanged():
    """Pure URL / path content (no remote_content) retains its prior hash — backward compat."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    content_a = Content(url="https://example.com/doc.pdf", name="Doc")
    content_b = Content(url="https://example.com/doc.pdf", name="Doc")

    # Identical (no remote_content on either) → identical hash, preserves dedup behavior.
    assert knowledge._build_content_hash(content_a) == knowledge._build_content_hash(content_b)


def test_text_content_different_values_produce_different_hashes():
    """Regression: ainsert(text_content=X) creates FileData(content=X, type='Text').
    Two calls with different text produce FileData with filename=None, type='Text'.
    The old if-elif chain hits ``elif file_data.type`` and appends only ``'Text'``
    for both inputs, causing a hash collision.  The fix must hash actual content
    bytes so that distinct text strings yield distinct hashes.
    """
    knowledge = Knowledge(vector_db=MockVectorDb())
    # Reproduce exactly what ainsert() builds for text_content:
    #   FileData(content=text_content, type="Text")  (filename=None, size=None)
    content1 = Content(file_data=FileData(content="Hello, world!", type="Text"))
    content2 = Content(file_data=FileData(content="Completely different text.", type="Text"))

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    assert hash1 != hash2, (
        "Different text_content values must produce different hashes. "
        "Hash collision: both hashed to the same value because only the type "
        "string 'Text' was used instead of the actual content bytes."
    )


def test_same_text_content_produces_same_hash():
    """Identical text_content must still deduplicate (stable hash)."""
    knowledge = Knowledge(vector_db=MockVectorDb())
    content1 = Content(file_data=FileData(content="Hello, world!", type="Text"))
    content2 = Content(file_data=FileData(content="Hello, world!", type="Text"))

    assert knowledge._build_content_hash(content1) == knowledge._build_content_hash(content2)


def test_same_path_different_metadata_produces_different_hashes():
    """Inserting the same document with different metadata and
    upsert=False must not collapse onto the same content identity
    """
    knowledge = Knowledge(vector_db=MockVectorDb())

    content1 = Content(path="./demo.pdf", metadata={"doc_id": 1, "collection_id": 1, "server_id": "10"})
    content2 = Content(path="./demo.pdf", metadata={"doc_id": 1, "collection_id": 1, "server_id": "11"})

    hash1 = knowledge._build_content_hash(content1)
    hash2 = knowledge._build_content_hash(content2)

    assert hash1 != hash2


def test_same_path_same_metadata_produces_same_hash():
    """Identical content + identical metadata must still dedup."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    metadata = {"doc_id": 1, "collection_id": 1, "server_id": "10"}
    content1 = Content(path="./demo.pdf", metadata=dict(metadata))
    content2 = Content(path="./demo.pdf", metadata=dict(metadata))

    assert knowledge._build_content_hash(content1) == knowledge._build_content_hash(content2)


def test_metadata_hash_independent_of_key_order():
    """The same metadata declared in a different key order must hash identically."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    content1 = Content(path="./demo.pdf", metadata={"doc_id": 1, "server_id": "10", "collection_id": 1})
    content2 = Content(path="./demo.pdf", metadata={"server_id": "10", "collection_id": 1, "doc_id": 1})

    assert knowledge._build_content_hash(content1) == knowledge._build_content_hash(content2)


def test_path_hash_without_metadata_backward_compatible():
    """A path with no metadata must hash the same as when no metadata segment is added."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    content_no_meta = Content(path="./demo.pdf")
    content_empty_meta = Content(path="./demo.pdf", metadata={})

    assert knowledge._build_content_hash(content_no_meta) == knowledge._build_content_hash(content_empty_meta)


def test_url_hash_with_metadata_differs_from_without():
    """Adding metadata to otherwise-identical URL content changes the hash."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    content_no_meta = Content(url="https://example.com/doc.pdf", name="Doc")
    content_with_meta = Content(url="https://example.com/doc.pdf", name="Doc", metadata={"tenant": "a"})

    assert knowledge._build_content_hash(content_no_meta) != knowledge._build_content_hash(content_with_meta)


def test_document_content_hash_includes_metadata():
    """Multi-page document hash also incorporates content metadata for uniqueness."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    content1 = Content(url="https://example.com", metadata={"server_id": "10"})
    content2 = Content(url="https://example.com", metadata={"server_id": "11"})

    doc = Document(content="Page content", meta_data={"url": "https://example.com/page"})

    hash1 = knowledge._build_document_content_hash(doc, content1)
    hash2 = knowledge._build_document_content_hash(doc, content2)

    assert hash1 != hash2
