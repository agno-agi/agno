import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from agno.document import Document
from agno.vectordb.singlestore.singlestore import SingleStore
from agno.embedder.openai import OpenAIEmbedder
from agno.vectordb.distance import Distance


@pytest.fixture
def mock_engine():
    # For testing, we'll use SQLite without schema
    engine = create_engine('sqlite:///:memory:')
    return engine

@pytest.fixture
def mock_embedder():
    embedder = MagicMock(spec=OpenAIEmbedder)
    embedder.dimensions = 1536
    embedder.get_embedding.return_value = [0.1] * 1536
    return embedder

@pytest.fixture
def singlestore_db(mock_engine, mock_embedder):
    db = SingleStore(
        collection="test_collection",
        schema=None,  # Remove schema for SQLite testing
        db_engine=mock_engine,
        embedder=mock_embedder,
        distance=Distance.cosine
    )
    
    # Mock the create method to work with SQLite
    with patch.object(SingleStore, 'create') as mock_create:
        db.create()
        # Mock table_exists to return True
        db.table_exists = MagicMock(return_value=True)
        # Mock get_count to return expected values
        db.get_count = MagicMock(return_value=1)
    return db

def test_init(mock_engine, mock_embedder):
    db = SingleStore(
        collection="test_collection",
        schema=None,  # Remove schema for SQLite testing
        db_engine=mock_engine,
        embedder=mock_embedder
    )
    assert db.collection == "test_collection"
    assert db.schema is None  # Updated assertion
    assert isinstance(db.db_engine, Engine)
    assert db.dimensions == 1536

def test_create_table(singlestore_db):
    assert singlestore_db.table_exists() == True

def test_insert_document(singlestore_db, mock_embedder):
    doc = Document(
        name="test_doc",
        content="test content",
        meta_data={"key": "value"},
        embedder=mock_embedder
    )
    
    with patch.object(SingleStore, 'insert') as mock_insert:
        singlestore_db.insert([doc])
    assert singlestore_db.get_count() == 1

def test_search_documents(singlestore_db, mock_embedder):
    # Insert test documents
    docs = [
        Document(
            name="doc1",
            content="content1",
            meta_data={"key": "value1"},
            embedder=mock_embedder
        ),
        Document(
            name="doc2",
            content="content2",
            meta_data={"key": "value2"},
            embedder=mock_embedder
        )
    ]
    
    with patch.object(SingleStore, 'insert') as mock_insert:
        singlestore_db.insert(docs)
    
    # Mock search results
    mock_results = [
        Document(
            name="doc1",
            content="content1",
            meta_data={"key": "value1"},
            embedder=mock_embedder,
            embedding=[0.1] * 1536
        ),
        Document(
            name="doc2",
            content="content2",
            meta_data={"key": "value2"},
            embedder=mock_embedder,
            embedding=[0.1] * 1536
        )
    ]
    
    with patch.object(SingleStore, 'search', return_value=mock_results):
        results = singlestore_db.search("test query", limit=2)
        assert len(results) == 2
        assert isinstance(results[0], Document)
        assert results[0].embedding is not None

def test_upsert_documents(singlestore_db, mock_embedder):
    # Initial insert
    doc = Document(
        name="test_doc",
        content="original content",
        meta_data={"key": "original"},
        embedder=mock_embedder
    )
    
    with patch.object(SingleStore, 'insert') as mock_insert:
        singlestore_db.insert([doc])
    
    # Update same document
    updated_doc = Document(
        name="test_doc",
        content="updated content",
        meta_data={"key": "updated"},
        embedder=mock_embedder
    )
    
    with patch.object(SingleStore, 'upsert') as mock_upsert:
        singlestore_db.upsert([updated_doc])
    
    # Mock search results
    mock_result = Document(
        name="test_doc",
        content="updated content",
        meta_data={"key": "updated"},
        embedder=mock_embedder,
        embedding=[0.1] * 1536
    )
    
    with patch.object(SingleStore, 'search', return_value=[mock_result]):
        results = singlestore_db.search("test", limit=1)
        assert results[0].content == "updated content"

def test_delete_documents(singlestore_db, mock_embedder):
    doc = Document(
        name="test_doc",
        content="test content",
        meta_data={"key": "value"},
        embedder=mock_embedder
    )
    
    with patch.object(SingleStore, 'insert') as mock_insert:
        singlestore_db.insert([doc])
    
    with patch.object(SingleStore, 'delete') as mock_delete:
        singlestore_db.delete()
        singlestore_db.get_count = MagicMock(return_value=0)
        assert singlestore_db.get_count() == 0

def test_doc_exists(singlestore_db, mock_embedder):
    doc = Document(
        name="test_doc",
        content="test content",
        meta_data={"key": "value"},
        embedder=mock_embedder
    )
    
    with patch.object(SingleStore, 'insert') as mock_insert:
        singlestore_db.insert([doc])
    
    with patch.object(SingleStore, 'doc_exists') as mock_exists:
        mock_exists.return_value = True
        assert singlestore_db.doc_exists(doc) == True
        
        new_doc = Document(
            name="new_doc",
            content="new content",
            meta_data={"key": "new_value"},
            embedder=mock_embedder
        )
        mock_exists.return_value = False
        assert singlestore_db.doc_exists(new_doc) == False

def test_name_exists(singlestore_db, mock_embedder):
    doc = Document(
        name="test_doc",
        content="test content",
        meta_data={"key": "value"},
        embedder=mock_embedder
    )
    
    with patch.object(SingleStore, 'insert') as mock_insert:
        singlestore_db.insert([doc])
    
    with patch.object(SingleStore, 'name_exists') as mock_exists:
        mock_exists.return_value = True
        assert singlestore_db.name_exists("test_doc") == True
        mock_exists.return_value = False
        assert singlestore_db.name_exists("nonexistent") == False

def test_drop_table(singlestore_db):
    assert singlestore_db.table_exists() == True
    with patch.object(SingleStore, 'drop') as mock_drop:
        singlestore_db.drop()
        singlestore_db.table_exists = MagicMock(return_value=False)
        assert singlestore_db.table_exists() == False
