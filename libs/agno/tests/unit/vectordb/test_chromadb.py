import os
import shutil
from typing import List

import pytest

from agno.document import Document
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.distance import Distance

TEST_COLLECTION = "test_collection"
TEST_PATH = "tmp/test_chromadb"


@pytest.fixture
def chroma_db(mock_embedder):
    """Fixture to create and clean up a ChromaDb instance"""
    # Ensure the test directory exists with proper permissions
    os.makedirs(TEST_PATH, exist_ok=True)

    # Clean up any existing data before the test
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = ChromaDb(collection=TEST_COLLECTION, path=TEST_PATH, persistent_client=False, embedder=mock_embedder)
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
            content="Tom Kha Gai is a Thai coconut soup with chicken", meta_data={"cuisine": "Thai", "type": "soup"}
        ),
        Document(content="Pad Thai is a stir-fried rice noodle dish", meta_data={"cuisine": "Thai", "type": "noodles"}),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"},
        ),
    ]


def test_create_collection(chroma_db):
    """Test creating a collection"""
    assert chroma_db.exists() is True
    assert chroma_db.get_count() == 0


def test_insert_documents(chroma_db, sample_documents):
    """Test inserting documents"""
    chroma_db.insert(sample_documents)
    assert chroma_db.get_count() == 3


def test_search_documents(chroma_db, sample_documents):
    """Test searching documents"""
    chroma_db.insert(sample_documents)

    # Search for coconut-related dishes
    results = chroma_db.search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("coconut" in doc.content.lower() for doc in results)


def test_upsert_documents(chroma_db, sample_documents):
    """Test upserting documents"""
    # Initial insert
    chroma_db.insert([sample_documents[0]])
    assert chroma_db.get_count() == 1

    # Upsert same document with different content
    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup", meta_data={"cuisine": "Thai", "type": "soup"}
    )
    chroma_db.upsert([modified_doc])

    # Search to verify the update
    results = chroma_db.search("spicy and sour", limit=1)
    assert len(results) == 1
    assert "spicy and sour" in results[0].content


def test_delete_collection(chroma_db, sample_documents):
    """Test deleting collection"""
    chroma_db.insert(sample_documents)
    assert chroma_db.get_count() == 3

    assert chroma_db.delete() is True
    assert chroma_db.exists() is False


def test_distance_metrics():
    """Test different distance metrics"""
    # Ensure the test directory exists
    os.makedirs(TEST_PATH, exist_ok=True)

    db_cosine = ChromaDb(collection="test_cosine", path=TEST_PATH, distance=Distance.cosine)
    db_cosine.create()

    db_euclidean = ChromaDb(collection="test_euclidean", path=TEST_PATH, distance=Distance.l2)
    db_euclidean.create()

    assert db_cosine._collection is not None
    assert db_euclidean._collection is not None

    # Cleanup
    try:
        db_cosine.drop()
        db_euclidean.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_doc_exists(chroma_db, sample_documents):
    """Test document existence check"""
    chroma_db.insert([sample_documents[0]])
    assert chroma_db.doc_exists(sample_documents[0]) is True


def test_get_count(chroma_db, sample_documents):
    """Test document count"""
    assert chroma_db.get_count() == 0
    chroma_db.insert(sample_documents)
    assert chroma_db.get_count() == 3


def test_error_handling(chroma_db):
    """Test error handling scenarios"""
    # Test search with invalid query
    results = chroma_db.search("")
    assert len(results) == 0

    # Test inserting empty document list
    chroma_db.insert([])
    assert chroma_db.get_count() == 0


def test_custom_embedder(mock_embedder):
    """Test using a custom embedder"""
    # Ensure the test directory exists
    os.makedirs(TEST_PATH, exist_ok=True)

    db = ChromaDb(collection=TEST_COLLECTION, path=TEST_PATH, embedder=mock_embedder)
    db.create()
    assert db.embedder == mock_embedder

    # Cleanup
    try:
        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_multiple_document_operations(chroma_db, sample_documents):
    """Test multiple document operations including batch inserts"""
    # Test batch insert
    first_batch = sample_documents[:2]
    chroma_db.insert(first_batch)
    assert chroma_db.get_count() == 2

    # Test adding another document
    second_batch = [sample_documents[2]]
    chroma_db.insert(second_batch)
    assert chroma_db.get_count() == 3

    # Verify all documents are searchable
    curry_results = chroma_db.search("curry", limit=1)
    assert len(curry_results) == 1
    assert "curry" in curry_results[0].content.lower()


@pytest.mark.asyncio
async def test_async_create_collection(chroma_db):
    """Test creating a collection asynchronously"""
    # First delete the collection created by the fixture
    chroma_db.delete()

    # Test async create
    await chroma_db.async_create()
    assert chroma_db.exists() is True
    assert chroma_db.get_count() == 0


@pytest.mark.asyncio
async def test_async_insert_documents(chroma_db, sample_documents):
    """Test inserting documents asynchronously"""
    await chroma_db.async_insert(sample_documents)
    assert chroma_db.get_count() == 3


@pytest.mark.asyncio
async def test_async_search_documents(chroma_db, sample_documents):
    """Test searching documents asynchronously"""
    await chroma_db.async_insert(sample_documents)

    # Search for coconut-related dishes
    results = await chroma_db.async_search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("coconut" in doc.content.lower() for doc in results)


@pytest.mark.asyncio
async def test_async_upsert_documents(chroma_db, sample_documents):
    """Test upserting documents asynchronously"""
    # Initial insert
    await chroma_db.async_insert([sample_documents[0]])
    assert chroma_db.get_count() == 1

    # Upsert same document with different content
    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup", meta_data={"cuisine": "Thai", "type": "soup"}
    )
    await chroma_db.async_upsert([modified_doc])

    # Search to verify the update
    results = await chroma_db.async_search("spicy and sour", limit=1)
    assert len(results) == 1
    assert "spicy and sour" in results[0].content


@pytest.mark.asyncio
async def test_async_doc_exists(chroma_db, sample_documents):
    """Test document existence check asynchronously"""
    await chroma_db.async_insert([sample_documents[0]])
    exists = await chroma_db.async_doc_exists(sample_documents[0])
    assert exists is True


@pytest.mark.asyncio
async def test_async_name_exists(chroma_db, sample_documents):
    """Test document name existence check asynchronously"""
    await chroma_db.async_insert([sample_documents[0]])
    exists = await chroma_db.async_name_exists(sample_documents[0].name)
    assert exists is False  # Expected to be False based on implementation


@pytest.mark.asyncio
async def test_async_drop_collection(chroma_db):
    """Test dropping collection asynchronously"""
    assert chroma_db.exists() is True
    await chroma_db.async_drop()
    assert chroma_db.exists() is False


@pytest.mark.asyncio
async def test_async_exists(chroma_db):
    """Test exists check asynchronously"""
    exists = await chroma_db.async_exists()
    assert exists is True

    # Delete the collection
    chroma_db.delete()

    exists = await chroma_db.async_exists()
    assert exists is False
