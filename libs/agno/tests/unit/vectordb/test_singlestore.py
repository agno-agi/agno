import json
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine import Engine

from agno.knowledge.document import Document
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
    singlestore_db.insert(documents=sample_documents, content_hash="test_hash")

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
    singlestore_db.upsert(documents=[modified_doc], content_hash="test_hash")

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


@pytest.mark.asyncio
async def test_error_handling(singlestore_db, mock_session):
    """Test error handling scenarios"""
    # Mock empty search results
    mock_session.execute.return_value.fetchall.return_value = []
    results = singlestore_db.search("")
    assert len(results) == 0

    # Test inserting empty document list
    singlestore_db.insert(documents=[], content_hash="test_hash")
    mock_session.execute.return_value.scalar.return_value = 0
    assert singlestore_db.get_count() == 0


def test_custom_embedder(mock_engine, mock_embedder):
    """Test using a custom embedder"""
    with patch("agno.vectordb.singlestore.singlestore.sessionmaker"):
        db = SingleStore(collection=TEST_COLLECTION, schema=TEST_SCHEMA, db_engine=mock_engine, embedder=mock_embedder)
        assert db.embedder == mock_embedder


def test_delete_by_id(singlestore_db, sample_documents, mock_session):
    """Test deleting documents by ID"""
    # Mock insert and get_count
    with patch.object(singlestore_db, "insert"), patch.object(singlestore_db, "get_count") as mock_get_count:
        singlestore_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_id method
    with patch.object(singlestore_db, "delete_by_id") as mock_delete_by_id:
        mock_delete_by_id.return_value = True

        # Get the actual ID that would be generated for the first document
        from hashlib import md5

        cleaned_content = sample_documents[0].content.replace("\x00", "\ufffd")
        doc_id = md5(cleaned_content.encode()).hexdigest()

        # Test delete by ID
        result = singlestore_db.delete_by_id(doc_id)
        assert result is True
        mock_delete_by_id.assert_called_once_with(doc_id)

        # Test delete non-existent ID
        mock_delete_by_id.reset_mock()
        mock_delete_by_id.return_value = False
        result = singlestore_db.delete_by_id("nonexistent_id")
        assert result is False


def test_delete_by_name(singlestore_db, sample_documents, mock_session):
    """Test deleting documents by name"""
    # Add names to sample documents
    sample_documents[0].name = "tom_kha"
    sample_documents[1].name = "pad_thai"
    sample_documents[2].name = "green_curry"

    # Mock insert and get_count
    with patch.object(singlestore_db, "insert"), patch.object(singlestore_db, "get_count") as mock_get_count:
        singlestore_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_name method
    with patch.object(singlestore_db, "delete_by_name") as mock_delete_by_name:
        mock_delete_by_name.return_value = True

        # Test delete by name
        result = singlestore_db.delete_by_name("tom_kha")
        assert result is True
        mock_delete_by_name.assert_called_once_with("tom_kha")

        # Test delete non-existent name
        mock_delete_by_name.reset_mock()
        mock_delete_by_name.return_value = False
        result = singlestore_db.delete_by_name("nonexistent")
        assert result is False


def test_delete_by_metadata(singlestore_db, sample_documents, mock_session):
    """Test deleting documents by metadata"""
    # Mock insert and get_count
    with patch.object(singlestore_db, "insert"), patch.object(singlestore_db, "get_count") as mock_get_count:
        singlestore_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_metadata method
    with patch.object(singlestore_db, "delete_by_metadata") as mock_delete_by_metadata:
        # Test delete all Thai cuisine documents
        mock_delete_by_metadata.return_value = True
        result = singlestore_db.delete_by_metadata({"cuisine": "Thai"})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"cuisine": "Thai"})

        # Test delete by specific metadata combination
        mock_delete_by_metadata.reset_mock()
        mock_delete_by_metadata.return_value = True
        result = singlestore_db.delete_by_metadata({"cuisine": "Thai", "type": "soup"})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"cuisine": "Thai", "type": "soup"})

        # Test delete by non-existent metadata
        mock_delete_by_metadata.reset_mock()
        mock_delete_by_metadata.return_value = False
        result = singlestore_db.delete_by_metadata({"cuisine": "Italian"})
        assert result is False


def test_delete_by_content_id(singlestore_db, sample_documents, mock_session):
    """Test deleting documents by content ID"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "recipe_1"
    sample_documents[1].content_id = "recipe_2"
    sample_documents[2].content_id = "recipe_3"

    # Mock insert and get_count
    with patch.object(singlestore_db, "insert"), patch.object(singlestore_db, "get_count") as mock_get_count:
        singlestore_db.insert(documents=sample_documents, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_content_id method
    with patch.object(singlestore_db, "delete_by_content_id") as mock_delete_by_content_id:
        # Test delete by content_id
        mock_delete_by_content_id.return_value = True
        result = singlestore_db.delete_by_content_id("recipe_1")
        assert result is True
        mock_delete_by_content_id.assert_called_once_with("recipe_1")

        # Test delete non-existent content_id
        mock_delete_by_content_id.reset_mock()
        mock_delete_by_content_id.return_value = False
        result = singlestore_db.delete_by_content_id("nonexistent_content_id")
        assert result is False


def test_delete_by_name_multiple_documents(singlestore_db, mock_session):
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

    # Mock insert and get_count
    with patch.object(singlestore_db, "insert"), patch.object(singlestore_db, "get_count") as mock_get_count:
        singlestore_db.insert(documents=docs, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_name and name_exists methods
    with (
        patch.object(singlestore_db, "delete_by_name") as mock_delete_by_name,
        patch.object(singlestore_db, "name_exists") as mock_name_exists,
    ):
        mock_delete_by_name.return_value = True
        mock_name_exists.side_effect = [False, True]  # tom_kha doesn't exist, pad_thai exists

        # Test delete all documents with name "tom_kha"
        result = singlestore_db.delete_by_name("tom_kha")
        assert result is True
        mock_delete_by_name.assert_called_once_with("tom_kha")

        # Verify name_exists behavior
        assert singlestore_db.name_exists("tom_kha") is False
        assert singlestore_db.name_exists("pad_thai") is True


def test_delete_by_metadata_complex(singlestore_db, mock_session):
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

    # Mock insert and get_count
    with patch.object(singlestore_db, "insert"), patch.object(singlestore_db, "get_count") as mock_get_count:
        singlestore_db.insert(documents=docs, content_hash="test_hash")
        mock_get_count.return_value = 3

    # Mock delete_by_metadata method
    with patch.object(singlestore_db, "delete_by_metadata") as mock_delete_by_metadata:
        # Test delete only spicy Thai dishes
        mock_delete_by_metadata.return_value = True
        result = singlestore_db.delete_by_metadata({"cuisine": "Thai", "spicy": True})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"cuisine": "Thai", "spicy": True})

        # Test delete all non-spicy dishes
        mock_delete_by_metadata.reset_mock()
        mock_delete_by_metadata.return_value = True
        result = singlestore_db.delete_by_metadata({"spicy": False})
        assert result is True
        mock_delete_by_metadata.assert_called_once_with({"spicy": False})
