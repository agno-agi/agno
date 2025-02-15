import json
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine import Engine

from agno.document import Document
from agno.vectordb.distance import Distance
from agno.vectordb.singlestore import SingleStore

TEST_COLLECTION = "test_collection"
TEST_SCHEMA = "test_schema"


@pytest.fixture
def mock_engine():
    """Fixture to create a mocked database engine"""
    mock_engine = MagicMock(spec=Engine)
    mock_engine.connect.return_value.__enter__.return_value = MagicMock()
    return mock_engine


@pytest.fixture
def mock_session():
    """Fixture to create a mocked database session"""
    mock_session = MagicMock()
    # Configure session context manager behavior
    mock_session.begin.return_value.__enter__.return_value = mock_session
    # Configure execute result with both scalar and fetchall methods
    mock_result = MagicMock()
    mock_result.scalar.return_value = True
    mock_result.fetchall.return_value = []
    mock_session.execute.return_value = mock_result
    # Configure first method
    mock_result.first.return_value = True
    return mock_session


@pytest.fixture
def singlestore_db(mock_engine, mock_session, mock_embedder):
    """Fixture to create a SingleStore instance with mocked components"""
    with patch("agno.vectordb.singlestore.singlestore.sessionmaker") as mock_sessionmaker:
        # Set up sessionmaker to return the mock session directly
        mock_sessionmaker.return_value = mock_session
        db = SingleStore(
            collection=TEST_COLLECTION,
            schema=TEST_SCHEMA,
            db_engine=mock_engine,
            embedder=mock_embedder,
        )
        db.create()
        yield db


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


def test_insert_documents(singlestore_db, sample_documents, mock_session):
    """Test inserting documents"""
    singlestore_db.insert(sample_documents)

    # Verify insert was called for each document
    assert mock_session.execute.call_count == len(sample_documents)

    # Verify commit was called
    mock_session.commit.assert_called_once()


def test_search_documents(singlestore_db, sample_documents, mock_session):
    """Test searching documents"""

    # Mock search results
    mock_result = [
        MagicMock(
            name="Doc1",
            meta_data=json.dumps({"cuisine": "Thai"}),
            content="Tom Kha Gai with coconut",
            embedding=json.dumps([0.1] * 1536),
            usage=json.dumps({}),
        ),
        MagicMock(
            name="Doc2",
            meta_data=json.dumps({"cuisine": "Thai"}),
            content="Green curry with coconut",
            embedding=json.dumps([0.1] * 1536),
            usage=json.dumps({}),
        ),
    ]
    mock_session.execute.return_value.fetchall.return_value = mock_result

    results = singlestore_db.search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("coconut" in doc.content.lower() for doc in results)


def test_upsert_documents(singlestore_db, sample_documents, mock_session):
    """Test upserting documents"""
    # Test upsert operation
    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup", meta_data={"cuisine": "Thai", "type": "soup"}
    )
    singlestore_db.upsert([modified_doc])

    # Verify upsert was called
    mock_session.execute.assert_called()
    mock_session.commit.assert_called_once()


def test_delete_collection(singlestore_db, mock_session):
    """Test deleting collection"""
    mock_session.execute.return_value.scalar.return_value = True
    assert singlestore_db.delete() is True


def test_distance_metrics(mock_engine):
    """Test different distance metrics"""
    with patch("agno.vectordb.singlestore.singlestore.sessionmaker"):
        db_cosine = SingleStore(
            collection="test_cosine", schema=TEST_SCHEMA, db_engine=mock_engine, distance=Distance.cosine
        )
        assert db_cosine.distance == Distance.cosine

        db_l2 = SingleStore(collection="test_l2", schema=TEST_SCHEMA, db_engine=mock_engine, distance=Distance.l2)
        assert db_l2.distance == Distance.l2


def test_doc_exists(singlestore_db, sample_documents, mock_session):
    """Test document existence check"""
    # Mock document exists
    mock_session.execute.return_value.first.return_value = True
    assert singlestore_db.doc_exists(sample_documents[0]) is True

    # Mock document doesn't exist
    mock_session.execute.return_value.first.return_value = None
    assert singlestore_db.doc_exists(sample_documents[0]) is False


@pytest.mark.asyncio
async def test_error_handling(singlestore_db, mock_session):
    """Test error handling scenarios"""
    # Mock empty search results
    mock_session.execute.return_value.fetchall.return_value = []
    results = singlestore_db.search("")
    assert len(results) == 0

    # Test inserting empty document list
    singlestore_db.insert([])
    mock_session.execute.return_value.scalar.return_value = 0
    assert singlestore_db.get_count() == 0


def test_custom_embedder(mock_engine, mock_embedder):
    """Test using a custom embedder"""
    with patch("agno.vectordb.singlestore.singlestore.sessionmaker"):
        db = SingleStore(collection=TEST_COLLECTION, schema=TEST_SCHEMA, db_engine=mock_engine, embedder=mock_embedder)
        assert db.embedder == mock_embedder
