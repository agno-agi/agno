import pytest
from typing import List
import os
import shutil
import tempfile

from agno.vectordb.chroma import ChromaDb
from agno.document import Document
from agno.embedder.openai import OpenAIEmbedder
from agno.vectordb.distance import Distance

TEST_COLLECTION = "test_collection"

@pytest.fixture
def test_dir():
    """Create a temporary directory for ChromaDB"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup after tests
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

@pytest.fixture
def chroma_db(test_dir):
    """Fixture to create and clean up a ChromaDb instance"""
    db = ChromaDb(
        collection=TEST_COLLECTION,
        path=test_dir,
        persistent_client=True
    )
    db.create()
    yield db
    # Cleanup
    try:
        db.drop()
    except Exception:
        pass  # Ignore cleanup errors

@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture to create sample documents"""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"}
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"}
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"}
        )
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
        content="Tom Kha Gai is a spicy and sour Thai coconut soup",
        meta_data={"cuisine": "Thai", "type": "soup"}
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

def test_distance_metrics(test_dir):
    """Test different distance metrics"""
    db_cosine = ChromaDb(
        collection="test_cosine",
        path=test_dir,
        distance=Distance.cosine
    )
    db_cosine.create()
    
    db_euclidean = ChromaDb(
        collection="test_euclidean", 
        path=test_dir,
        distance=Distance.l2
    )
    db_euclidean.create()
    
    assert db_cosine._collection is not None
    assert db_euclidean._collection is not None
    
    # Cleanup
    db_cosine.drop()
    db_euclidean.drop()

def test_doc_exists(chroma_db, sample_documents):
    """Test document existence check"""
    chroma_db.insert([sample_documents[0]])
    assert chroma_db.doc_exists(sample_documents[0]) is True

def test_get_count(chroma_db, sample_documents):
    """Test document count"""
    assert chroma_db.get_count() == 0
    chroma_db.insert(sample_documents)
    assert chroma_db.get_count() == 3

@pytest.mark.asyncio
async def test_error_handling(chroma_db):
    """Test error handling scenarios"""
    # Test search with invalid query
    results = chroma_db.search("")
    assert len(results) == 0
    
    # Test inserting empty document list
    chroma_db.insert([])
    assert chroma_db.get_count() == 0

def test_custom_embedder(test_dir):
    """Test using a custom embedder"""
    custom_embedder = OpenAIEmbedder()
    db = ChromaDb(
        collection=TEST_COLLECTION,
        path=test_dir,
        embedder=custom_embedder
    )
    db.create()
    assert db.embedder == custom_embedder
    db.drop()