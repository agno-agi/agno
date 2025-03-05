import os
import shutil
from typing import List

import pytest

from agno.document import Document
from agno.vectordb.lancedb import LanceDb
from agno.vectordb.search import SearchType

TEST_TABLE = "test_table"
TEST_PATH = "tmp/test_lancedb"


@pytest.fixture
def lance_db(mock_embedder):
    """Fixture to create and clean up a LanceDb instance"""
    # Ensure the test directory exists with proper permissions
    os.makedirs(TEST_PATH, exist_ok=True)

    # Clean up any existing data before the test
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = LanceDb(uri=TEST_PATH, table_name=TEST_TABLE, embedder=mock_embedder)
    db.create()
    yield db

    # Cleanup after test
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
    lance_db.insert(sample_documents)
    assert lance_db.get_count() == 3


def test_vector_search(lance_db, sample_documents):
    """Test vector search"""
    lance_db.insert(sample_documents)

    # Search for coconut-related dishes
    results = lance_db.vector_search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("coconut" in doc.content.lower() for doc in results)


def test_keyword_search(lance_db, sample_documents):
    """Test keyword search"""
    lance_db.search_type = SearchType.keyword
    lance_db.insert(sample_documents)

    results = lance_db.search("spicy curry", limit=1)
    assert len(results) == 1
    assert "curry" in results[0].content.lower()


def test_hybrid_search(lance_db, sample_documents):
    """Test hybrid search"""
    lance_db.search_type = SearchType.hybrid
    lance_db.insert(sample_documents)

    results = lance_db.search("Thai soup", limit=2)
    assert len(results) == 2
    assert any("thai" in doc.content.lower() for doc in results)


def test_upsert_documents(lance_db, sample_documents):
    """Test upserting documents"""
    # Initial insert
    lance_db.insert([sample_documents[0]])
    assert lance_db.get_count() == 1

    # Upsert same document with different content
    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup",
        meta_data={"cuisine": "Thai", "type": "soup"},
        name="tom_kha",
    )
    lance_db.upsert([modified_doc])

    # Search to verify the update
    results = lance_db.search("spicy and sour", limit=1)
    assert len(results) == 1
    assert results[0].content is not None


def test_doc_exists(lance_db, sample_documents):
    """Test document existence check"""
    lance_db.insert([sample_documents[0]])
    assert lance_db.doc_exists(sample_documents[0]) is True


def test_name_exists(lance_db, sample_documents):
    """Test name existence check"""
    lance_db.insert([sample_documents[0]])
    assert lance_db.name_exists("tom_kha") is True
    assert lance_db.name_exists("nonexistent") is False


def test_get_count(lance_db, sample_documents):
    """Test document count"""
    assert lance_db.get_count() == 0
    lance_db.insert(sample_documents)
    assert lance_db.get_count() == 3


def test_error_handling(lance_db):
    """Test error handling scenarios"""
    # Test search with empty query
    results = lance_db.search("")
    assert len(results) == 0

    # Test inserting empty document list
    lance_db.insert([])
    assert lance_db.get_count() == 0


def test_bad_vectors_handling(mock_embedder):
    """Test handling of bad vectors"""
    db = LanceDb(
        uri=TEST_PATH, table_name="test_bad_vectors", on_bad_vectors="fill", fill_value=0.0, embedder=mock_embedder
    )
    db.create()

    try:
        # Test with a document that might have bad vectors
        doc = Document(content="Test document", meta_data={}, name="test")
        db.insert([doc])
        assert db.get_count() == 1
    finally:
        db.drop()
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)
