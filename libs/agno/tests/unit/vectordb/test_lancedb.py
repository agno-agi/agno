import os
import shutil
from typing import List

import pytest

from agno.knowledge.document import Document
from agno.vectordb.lancedb import LanceDb
from agno.vectordb.search import SearchType

TEST_TABLE = "test_table"
TEST_PATH = "tmp/test_lancedb"


@pytest.fixture
def lance_db(mock_embedder):
    """Fixture to create and clean up a LanceDb instance"""
    os.makedirs(TEST_PATH, exist_ok=True)
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = LanceDb(uri=TEST_PATH, table_name=TEST_TABLE, embedder=mock_embedder)
    db.create()
    yield db

    try:
        db.drop()
    except Exception:
        pass

    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture to create sample documents"""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"},
            name="tom_kha",
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"},
            name="pad_thai",
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"},
            name="green_curry",
        ),
    ]


def test_create_table(lance_db):
    """Test creating a table"""
    assert lance_db.exists() is True
    assert lance_db.get_count() == 0


def test_insert_documents(lance_db, sample_documents):
    """Test inserting documents"""
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3


def test_vector_search(lance_db, sample_documents):
    """Test vector search"""
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    results = lance_db.vector_search("coconut dishes", limit=2)
    assert results is not None
    assert len(results) == 2
    # results is a list of dicts (LanceDB .to_list()), check payload for content
    import json

    found = False
    for row in results:
        payload = json.loads(row["payload"])
        if "coconut" in payload["content"].lower():
            found = True
            break
    assert found


def test_keyword_search(lance_db, sample_documents):
    """Test keyword search"""
    lance_db.search_type = SearchType.keyword
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    results = lance_db.search("spicy curry", limit=1)
    assert len(results) == 1
    assert "curry" in results[0].content.lower()


def test_hybrid_search(lance_db, sample_documents):
    """Test hybrid search"""
    lance_db.search_type = SearchType.hybrid
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    results = lance_db.search("Thai soup", limit=2)
    assert len(results) == 2
    assert any("thai" in doc.content.lower() for doc in results)


def test_upsert_documents(lance_db, sample_documents):
    """Test upserting documents"""
    lance_db.insert(documents=[sample_documents[0]], content_hash="test_hash")
    assert lance_db.get_count() == 1

    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup",
        meta_data={"cuisine": "Thai", "type": "soup"},
        name="tom_kha",
    )
    lance_db.upsert(documents=[modified_doc], content_hash="test_hash")
    results = lance_db.search("spicy and sour", limit=1)
    assert len(results) == 1
    assert results[0].content is not None


def test_name_exists(lance_db, sample_documents):
    """Test name existence check"""
    lance_db.insert(documents=[sample_documents[0]], content_hash="test_hash")
    assert lance_db.name_exists("tom_kha") is True
    assert lance_db.name_exists("nonexistent") is False


def test_id_exists(lance_db, sample_documents):
    """Test ID existence check"""
    content_hash = "test_hash"
    lance_db.insert(documents=[sample_documents[0]], content_hash=content_hash)

    # Get the actual ID that was generated (MD5 hash of base_id_content_hash)
    from hashlib import md5

    cleaned_content = sample_documents[0].content.replace("\x00", "\ufffd")
    base_id = sample_documents[0].id or md5(cleaned_content.encode()).hexdigest()
    expected_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

    assert lance_db.id_exists(expected_id) is True
    assert lance_db.id_exists("nonexistent_id") is False


def test_delete_by_id(lance_db, sample_documents):
    """Test deleting documents by ID"""
    content_hash = "test_hash"
    lance_db.insert(documents=sample_documents, content_hash=content_hash)
    assert lance_db.get_count() == 3

    # Get the actual ID that was generated for the first document
    from hashlib import md5

    cleaned_content = sample_documents[0].content.replace("\x00", "\ufffd")
    base_id = sample_documents[0].id or md5(cleaned_content.encode()).hexdigest()
    doc_id = md5(f"{base_id}_{content_hash}".encode()).hexdigest()

    # Delete by ID
    result = lance_db.delete_by_id(doc_id)
    assert result is True
    assert lance_db.get_count() == 2
    assert lance_db.id_exists(doc_id) is False

    # Try to delete non-existent ID
    result = lance_db.delete_by_id("nonexistent_id")
    assert result is True  # LanceDB delete doesn't fail for non-existent IDs
    assert lance_db.get_count() == 2


def test_delete_by_name(lance_db, sample_documents):
    """Test deleting documents by name"""
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Delete by name
    result = lance_db.delete_by_name("tom_kha")
    assert result is True
    assert lance_db.get_count() == 2
    assert lance_db.name_exists("tom_kha") is False

    # Try to delete non-existent name
    result = lance_db.delete_by_name("nonexistent")
    assert result is False
    assert lance_db.get_count() == 2


def test_delete_by_metadata(lance_db, sample_documents):
    """Test deleting documents by metadata"""
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Delete by metadata - should delete all Thai cuisine documents
    result = lance_db.delete_by_metadata({"cuisine": "Thai"})
    assert result is True
    assert lance_db.get_count() == 0

    # Insert again and test partial metadata match
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Delete by specific metadata combination
    result = lance_db.delete_by_metadata({"cuisine": "Thai", "type": "soup"})
    assert result is True
    assert lance_db.get_count() == 2  # Should only delete tom_kha

    # Try to delete by non-existent metadata
    result = lance_db.delete_by_metadata({"cuisine": "Italian"})
    assert result is False
    assert lance_db.get_count() == 2


def test_delete_by_content_id(lance_db, sample_documents):
    """Test deleting documents by content ID"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "recipe_1"
    sample_documents[1].content_id = "recipe_2"
    sample_documents[2].content_id = "recipe_3"

    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Delete by content_id
    result = lance_db.delete_by_content_id("recipe_1")
    assert result is True
    assert lance_db.get_count() == 2

    # Try to delete non-existent content_id
    result = lance_db.delete_by_content_id("nonexistent_content_id")
    assert result is False
    assert lance_db.get_count() == 2


def test_delete_by_name_multiple_documents(lance_db):
    """Test deleting multiple documents with the same name"""
    # Create multiple documents with the same name
    docs = [
        Document(
            content="First version of Tom Kha Gai",
            meta_data={"version": "1"},
            name="tom_kha",
            content_id="recipe_1_v1",
        ),
        Document(
            content="Second version of Tom Kha Gai",
            meta_data={"version": "2"},
            name="tom_kha",
            content_id="recipe_1_v2",
        ),
        Document(
            content="Pad Thai recipe",
            meta_data={"version": "1"},
            name="pad_thai",
            content_id="recipe_2_v1",
        ),
    ]

    lance_db.insert(documents=docs, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Delete all documents with name "tom_kha"
    result = lance_db.delete_by_name("tom_kha")
    assert result is True
    assert lance_db.get_count() == 1
    assert lance_db.name_exists("tom_kha") is False
    assert lance_db.name_exists("pad_thai") is True


def test_delete_by_metadata_complex(lance_db):
    """Test deleting documents with complex metadata matching"""
    docs = [
        Document(
            content="Thai soup recipe",
            meta_data={"cuisine": "Thai", "type": "soup", "spicy": True},
            name="recipe_1",
        ),
        Document(
            content="Thai noodle recipe",
            meta_data={"cuisine": "Thai", "type": "noodles", "spicy": False},
            name="recipe_2",
        ),
        Document(
            content="Italian pasta recipe",
            meta_data={"cuisine": "Italian", "type": "pasta", "spicy": False},
            name="recipe_3",
        ),
    ]

    lance_db.insert(documents=docs, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Delete only spicy Thai dishes
    result = lance_db.delete_by_metadata({"cuisine": "Thai", "spicy": True})
    assert result is True
    assert lance_db.get_count() == 2

    # Delete all non-spicy dishes
    result = lance_db.delete_by_metadata({"spicy": False})
    assert result is True
    assert lance_db.get_count() == 0


def test_get_count(lance_db, sample_documents):
    """Test document count"""
    assert lance_db.get_count() == 0
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3


def test_error_handling(lance_db):
    """Test error handling scenarios"""
    results = lance_db.search("")
    assert len(results) == 0
    lance_db.insert(documents=[], content_hash="test_hash")
    assert lance_db.get_count() == 0


def test_bad_vectors_handling(mock_embedder):
    """Test handling of bad vectors"""
    db = LanceDb(
        uri=TEST_PATH, table_name="test_bad_vectors", on_bad_vectors="fill", fill_value=0.0, embedder=mock_embedder
    )
    db.create()
    try:
        doc = Document(content="Test document", meta_data={}, name="test")
        db.insert(documents=[doc], content_hash="test_hash")
        assert db.get_count() == 1
    finally:
        db.drop()
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_update_metadata(lance_db, sample_documents):
    """Test updating metadata for documents with specific content_id"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "doc_1"
    sample_documents[1].content_id = "doc_2"
    sample_documents[2].content_id = "doc_3"

    # Insert documents
    lance_db.insert(documents=sample_documents, content_hash="test_hash")
    assert lance_db.get_count() == 3

    # Update metadata for a specific content_id
    new_metadata = {"updated": True, "version": "2.0", "cuisine": "Thai"}
    lance_db.update_metadata("doc_1", new_metadata)

    # Verify the metadata was updated by searching and checking the results
    import json

    total_count = lance_db.table.count_rows()
    result = lance_db.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

    updated_doc_found = False
    for _, row in result.iterrows():
        payload = json.loads(row["payload"])
        if payload.get("content_id") == "doc_1":
            # Check that the metadata was merged correctly
            assert payload["meta_data"]["updated"] is True
            assert payload["meta_data"]["version"] == "2.0"
            assert payload["meta_data"]["cuisine"] == "Thai"  # Should merge with existing
            assert payload["meta_data"]["type"] == "soup"  # Original metadata should remain
            updated_doc_found = True
            break

    assert updated_doc_found, "Updated document not found"


def test_update_metadata_nonexistent_content_id(lance_db, sample_documents):
    """Test updating metadata for non-existent content_id"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "doc_1"

    # Insert documents
    lance_db.insert(documents=sample_documents[:1], content_hash="test_hash")
    assert lance_db.get_count() == 1

    # Try to update metadata for non-existent content_id (should not raise error)
    new_metadata = {"updated": True}
    lance_db.update_metadata("nonexistent_id", new_metadata)

    # Count should remain the same
    assert lance_db.get_count() == 1


def test_update_metadata_empty_metadata(lance_db, sample_documents):
    """Test updating with empty metadata"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "doc_1"

    # Insert documents
    lance_db.insert(documents=sample_documents[:1], content_hash="test_hash")
    assert lance_db.get_count() == 1

    # Update with empty metadata
    lance_db.update_metadata("doc_1", {})

    # Should not cause any errors
    assert lance_db.get_count() == 1


def test_update_metadata_multiple_documents_same_content_id(lance_db):
    """Test updating metadata when multiple documents have the same content_id"""
    # Create multiple documents with the same content_id
    docs = [
        Document(
            content="First version of recipe",
            meta_data={"version": "1.0"},
            name="recipe_v1",
            content_id="shared_content_id",
        ),
        Document(
            content="Second version of recipe",
            meta_data={"version": "2.0"},
            name="recipe_v2",
            content_id="shared_content_id",
        ),
    ]

    lance_db.insert(documents=docs, content_hash="test_hash")
    assert lance_db.get_count() == 2

    # Update metadata for the shared content_id
    new_metadata = {"updated": True, "status": "reviewed"}
    lance_db.update_metadata("shared_content_id", new_metadata)

    # Verify both documents were updated
    import json

    total_count = lance_db.table.count_rows()
    result = lance_db.table.search().select(["id", "payload"]).limit(total_count).to_pandas()

    updated_count = 0
    for _, row in result.iterrows():
        payload = json.loads(row["payload"])
        if payload.get("content_id") == "shared_content_id":
            assert payload["meta_data"]["updated"] is True
            assert payload["meta_data"]["status"] == "reviewed"
            updated_count += 1

    assert updated_count == 2, "Both documents should have been updated"


def test_content_hash_exists(lance_db, sample_documents):
    """Test content_hash_exists method"""
    test_hash = "test_content_hash_123"

    # Should return False when hash doesn't exist
    assert lance_db.content_hash_exists(test_hash) is False

    # Insert documents with the test hash
    lance_db.insert(documents=sample_documents[:1], content_hash=test_hash)

    # Should return True when hash exists
    assert lance_db.content_hash_exists(test_hash) is True

    # Should still return False for non-existent hash
    assert lance_db.content_hash_exists("nonexistent_hash") is False


def test_update_metadata_preserves_vector(lance_db, sample_documents):
    """Test that update_metadata preserves the vector embedding"""

    sample_documents[0].content_id = "test_doc"
    lance_db.insert(documents=sample_documents[:1], content_hash="test_hash")

    # Get vector before update
    total_count = lance_db.table.count_rows()
    result_before = lance_db.table.search().select(["id", "payload", "vector"]).limit(total_count).to_pandas()
    vector_before = result_before.iloc[0]["vector"]
    assert vector_before is not None
    assert len(vector_before) == 1024

    # Update metadata
    lance_db.update_metadata("test_doc", {"new_field": "new_value"})

    # Get vector after update
    result_after = lance_db.table.search().select(["id", "payload", "vector"]).limit(total_count).to_pandas()
    vector_after = result_after.iloc[0]["vector"]

    assert vector_after is not None
    assert len(vector_after) == 1024
    assert list(vector_before) == list(vector_after)


def test_insert_reembeds_empty_embedding(lance_db):
    """Test that insert re-embeds documents with empty embedding list"""
    doc = Document(
        content="Test document",
        meta_data={"test": "value"},
        name="test_doc",
    )
    doc.embedding = []  # Simulate failed async embedding

    lance_db.insert(documents=[doc], content_hash="test_hash")

    total_count = lance_db.table.count_rows()
    result = lance_db.table.search().select(["vector"]).limit(total_count).to_pandas()

    assert len(result) == 1
    vector = result.iloc[0]["vector"]
    assert vector is not None
    assert len(vector) == 1024


def test_get_table_names_new(lance_db):
    """Test _get_table_names uses list_tables()"""
    from unittest.mock import MagicMock

    mock_conn = MagicMock()
    mock_conn.list_tables.return_value = MagicMock(tables=["table1", "table2"])

    result = lance_db._get_table_names(mock_conn)

    mock_conn.list_tables.assert_called_once()
    assert result == ["table1", "table2"]


def test_get_table_names_old(lance_db):
    """Test _get_table_names falls back to table_names() for old LanceDB versions"""
    from unittest.mock import MagicMock

    mock_conn = MagicMock(spec=["table_names"])  # No list_tables attribute
    mock_conn.table_names.return_value = ["old_table1", "old_table2"]

    result = lance_db._get_table_names(mock_conn)

    mock_conn.table_names.assert_called_once()
    assert result == ["old_table1", "old_table2"]
