import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.document import Document
from agno.vectordb.clickhouse import Clickhouse

# Configuration for tests
TEST_TABLE = f"test_clickhouse_{uuid.uuid4().hex[:8]}"
TEST_DB = "test_db"


@pytest.fixture
def mock_client():
    """Create a mock Clickhouse client."""
    client = MagicMock()
    client.command.return_value = None

    # Mock query results
    query_result = MagicMock()
    query_result.result_rows = []
    client.query.return_value = query_result

    return client


@pytest.fixture
def mock_async_client():
    """Create a mock Clickhouse async client."""
    async_client = AsyncMock()
    async_client.command.return_value = None

    # Mock query results
    query_result = MagicMock()
    query_result.result_rows = []
    async_client.query.return_value = query_result

    return async_client


@pytest.fixture
def mock_clickhouse(mock_client, mock_async_client, mock_embedder):
    """Create a Clickhouse instance with mocked dependencies."""
    with patch("clickhouse_connect.get_client", return_value=mock_client):
        db = Clickhouse(
            table_name=TEST_TABLE,
            host="localhost",
            database_name=TEST_DB,
            embedder=mock_embedder,
            client=mock_client,
            asyncclient=mock_async_client,
        )

        yield db


def create_test_documents(num_docs=3):
    """Helper to create test documents."""
    return [
        Document(
            id=f"doc_{i}",
            content=f"This is test document {i}",
            meta_data={"type": "test", "index": i},
            name=f"test_doc_{i}",
        )
        for i in range(num_docs)
    ]


# Synchronous Tests
def test_initialization():
    """Test basic initialization."""
    client = MagicMock()
    embedder = MagicMock()

    db = Clickhouse(table_name=TEST_TABLE, host="localhost", database_name=TEST_DB, embedder=embedder, client=client)

    assert db.table_name == TEST_TABLE
    assert db.database_name == TEST_DB
    assert db.client == client
    assert db.embedder == embedder


def test_table_exists(mock_clickhouse):
    """Test table_exists method."""
    # Test when table doesn't exist
    mock_clickhouse.client.command.return_value = 0

    assert mock_clickhouse.table_exists() is False
    mock_clickhouse.client.command.assert_called()

    # Test when table exists
    mock_clickhouse.client.command.return_value = 1

    assert mock_clickhouse.table_exists() is True


def test_create(mock_clickhouse):
    """Test create method."""
    # Test when table doesn't exist
    with patch.object(mock_clickhouse, "table_exists", return_value=False):
        mock_clickhouse.create()

        # Verify command was called to create database
        mock_clickhouse.client.command.assert_called()

    # Test when table exists
    with patch.object(mock_clickhouse, "table_exists", return_value=True):
        mock_clickhouse.client.command.reset_mock()
        mock_clickhouse.create()

        # Verify command was not called
        assert not mock_clickhouse.client.command.called


def test_doc_exists(mock_clickhouse):
    """Test doc_exists method."""
    doc = create_test_documents(1)[0]

    # Test when document doesn't exist
    query_result = MagicMock()
    query_result.result_rows = []
    mock_clickhouse.client.query.return_value = query_result

    assert mock_clickhouse.doc_exists(doc) is False
    mock_clickhouse.client.query.assert_called()

    # Test when document exists
    query_result.result_rows = [["hash123"]]
    mock_clickhouse.client.query.return_value = query_result

    assert mock_clickhouse.doc_exists(doc) is True


def test_name_exists(mock_clickhouse):
    """Test name_exists method."""
    # Test when name doesn't exist
    query_result = MagicMock()
    query_result.result_rows = []
    # Mock bool(result) to return False for empty results
    query_result.__bool__ = lambda self: bool(self.result_rows)
    mock_clickhouse.client.query.return_value = query_result

    assert mock_clickhouse.name_exists("test_name") is False
    mock_clickhouse.client.query.assert_called()

    # Test when name exists
    query_result = MagicMock()
    query_result.result_rows = [["test_name"]]
    mock_clickhouse.client.query.return_value = query_result

    assert mock_clickhouse.name_exists("test_name") is True


def test_id_exists(mock_clickhouse):
    """Test id_exists method."""
    # Test when ID doesn't exist
    query_result = MagicMock()
    query_result.result_rows = []
    # Mock bool(result) to return False for empty results
    query_result.__bool__ = lambda self: bool(query_result.result_rows)
    mock_clickhouse.client.query.return_value = query_result

    assert mock_clickhouse.id_exists("test_id") is False
    mock_clickhouse.client.query.assert_called()

    # Test when ID exists
    query_result = MagicMock()
    query_result.result_rows = [["test_id"]]
    mock_clickhouse.client.query.return_value = query_result

    assert mock_clickhouse.id_exists("test_id") is True


def test_insert(mock_clickhouse, mock_embedder):
    """Test insert method."""
    docs = create_test_documents(2)

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Test insert
    mock_clickhouse.insert(docs)

    # Check that client.insert was called with the right arguments
    mock_clickhouse.client.insert.assert_called_once()

    # Validate the call parameters
    call_args = mock_clickhouse.client.insert.call_args
    assert f"{TEST_DB}.{TEST_TABLE}" in call_args[0]
    assert len(call_args[0][1]) == 2  # 2 documents inserted


def test_upsert(mock_clickhouse):
    """Test upsert method."""
    docs = create_test_documents(2)

    # Test upsert by patching insert
    with patch.object(mock_clickhouse, "insert") as mock_insert:
        mock_clickhouse.upsert(docs)

        # Check that insert was called
        mock_insert.assert_called_once_with(documents=docs, filters=None)
        # Check that query was called to finalize the upsert
        mock_clickhouse.client.query.assert_called_once()


def test_search(mock_clickhouse, mock_embedder):
    """Test search method."""
    query = "test query"

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Mock query results
    query_result = MagicMock()
    query_result.result_rows = [
        ["test_name_1", {"type": "test"}, "Test content 1", [0.1] * 1024, {}],
        ["test_name_2", {"type": "test"}, "Test content 2", [0.2] * 1024, {}],
    ]
    mock_clickhouse.client.query.return_value = query_result

    # Test search
    results = mock_clickhouse.search(query, limit=2)

    # Check that embedder.get_embedding was called
    mock_embedder.get_embedding.assert_called_with(query)

    # Check that client.query was called
    mock_clickhouse.client.query.assert_called_once()

    # Check the results
    assert len(results) == 2
    assert results[0].name == "test_name_1"
    assert results[0].content == "Test content 1"
    assert results[1].name == "test_name_2"
    assert results[1].content == "Test content 2"


def test_drop(mock_clickhouse):
    """Test drop method."""
    # Test when table exists
    with patch.object(mock_clickhouse, "table_exists", return_value=True):
        mock_clickhouse.drop()

        # Verify command was called to drop table
        mock_clickhouse.client.command.assert_called_once()

    # Test when table doesn't exist
    with patch.object(mock_clickhouse, "table_exists", return_value=False):
        mock_clickhouse.client.command.reset_mock()
        mock_clickhouse.drop()

        # Verify command was not called
        assert not mock_clickhouse.client.command.called


def test_exists(mock_clickhouse):
    """Test exists method."""
    with patch.object(mock_clickhouse, "table_exists") as mock_table_exists:
        # Test when table exists
        mock_table_exists.return_value = True
        assert mock_clickhouse.exists() is True

        # Test when table doesn't exist
        mock_table_exists.return_value = False
        assert mock_clickhouse.exists() is False


def test_get_count(mock_clickhouse):
    """Test get_count method."""
    # Mock query results
    query_result = MagicMock()
    query_result.first_row = [42]
    mock_clickhouse.client.query.return_value = query_result

    # Test get_count
    count = mock_clickhouse.get_count()

    # Check result
    assert count == 42
    mock_clickhouse.client.query.assert_called_once()


def test_delete(mock_clickhouse):
    """Test delete method."""
    # Test delete
    result = mock_clickhouse.delete()

    assert result is True
    mock_clickhouse.client.command.assert_called_once()


def test_optimize(mock_clickhouse):
    """Test optimize method."""
    # There's no actual logic to test here, but we can verify it doesn't crash
    mock_clickhouse.optimize()


# Asynchronous Tests
@pytest.mark.asyncio
async def test_ensure_async_client(mock_clickhouse):
    """Test _ensure_async_client method."""
    # Test when async_client is already set
    result = await mock_clickhouse._ensure_async_client()
    assert result == mock_clickhouse.async_client

    # Test when async_client is not set
    mock_clickhouse.async_client = None
    with patch("clickhouse_connect.get_async_client", return_value=AsyncMock()) as mock_get_async_client:
        result = await mock_clickhouse._ensure_async_client()
        mock_get_async_client.assert_called_once()
        assert result == mock_clickhouse.async_client


@pytest.mark.asyncio
async def test_async_table_exists(mock_clickhouse):
    """Test async_table_exists method."""
    # Test when table doesn't exist
    mock_clickhouse.async_client.command.return_value = 0

    assert await mock_clickhouse.async_table_exists() is False

    # Test when table exists
    mock_clickhouse.async_client.command.return_value = 1

    assert await mock_clickhouse.async_table_exists() is True


@pytest.mark.asyncio
async def test_async_create(mock_clickhouse):
    """Test async_create method."""
    # Test when table doesn't exist
    with patch.object(mock_clickhouse, "async_table_exists", return_value=False):
        await mock_clickhouse.async_create()

        # Verify command was called to create database
        assert mock_clickhouse.async_client.command.called

    # Test when table exists
    with patch.object(mock_clickhouse, "async_table_exists", return_value=True):
        mock_clickhouse.async_client.command.reset_mock()
        await mock_clickhouse.async_create()

        # Verify command was not called
        assert not mock_clickhouse.async_client.command.called


@pytest.mark.asyncio
async def test_async_doc_exists(mock_clickhouse):
    """Test async_doc_exists method."""
    doc = create_test_documents(1)[0]

    # Test when document doesn't exist
    query_result = MagicMock()
    query_result.result_rows = []
    mock_clickhouse.async_client.query.return_value = query_result

    assert await mock_clickhouse.async_doc_exists(doc) is False

    # Test when document exists
    query_result.result_rows = [["hash123"]]
    mock_clickhouse.async_client.query.return_value = query_result

    assert await mock_clickhouse.async_doc_exists(doc) is True


@pytest.mark.asyncio
async def test_async_name_exists(mock_clickhouse):
    """Test async_name_exists method."""
    # Test when name doesn't exist
    query_result = MagicMock()
    query_result.result_rows = []
    # Mock bool(result) to return False for empty results
    query_result.__bool__ = lambda self: bool(self.result_rows)
    mock_clickhouse.async_client.query.return_value = query_result

    assert await mock_clickhouse.async_name_exists("test_name") is False

    # Test when name exists
    query_result = MagicMock()
    query_result.result_rows = [["test_name"]]
    mock_clickhouse.async_client.query.return_value = query_result

    assert await mock_clickhouse.async_name_exists("test_name") is True


@pytest.mark.asyncio
async def test_async_insert(mock_clickhouse, mock_embedder):
    """Test async_insert method."""
    docs = create_test_documents(2)

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Test async_insert
    await mock_clickhouse.async_insert(docs)

    # Check that async_client.insert was called with the right arguments
    mock_clickhouse.async_client.insert.assert_called_once()

    # Validate the call parameters
    call_args = mock_clickhouse.async_client.insert.call_args
    assert f"{TEST_DB}.{TEST_TABLE}" in call_args[0]
    assert len(call_args[0][1]) == 2  # 2 documents inserted


@pytest.mark.asyncio
async def test_async_upsert(mock_clickhouse):
    """Test async_upsert method."""
    docs = create_test_documents(2)

    # Test async_upsert by patching async_insert
    with patch.object(mock_clickhouse, "async_insert") as mock_async_insert:
        # Configure the mock to return a coroutine
        mock_async_insert.return_value = None

        await mock_clickhouse.async_upsert(docs)

        # Check that async_insert was called
        mock_async_insert.assert_called_once_with(documents=docs, filters=None)
        # Check that query was called to finalize the upsert
        mock_clickhouse.async_client.query.assert_called_once()


@pytest.mark.asyncio
async def test_async_search(mock_clickhouse, mock_embedder):
    """Test async_search method."""
    query = "test query"

    # Mock embedder
    mock_embedder.get_embedding.return_value = [0.1] * 1024

    # Mock query results
    query_result = MagicMock()
    query_result.result_rows = [
        ["test_name_1", {"type": "test"}, "Test content 1", [0.1] * 1024, {}],
        ["test_name_2", {"type": "test"}, "Test content 2", [0.2] * 1024, {}],
    ]
    mock_clickhouse.async_client.query.return_value = query_result

    # Test async_search
    results = await mock_clickhouse.async_search(query, limit=2)

    # Check that embedder.get_embedding was called
    mock_embedder.get_embedding.assert_called_with(query)

    # Check that async_client.query was called
    mock_clickhouse.async_client.query.assert_called_once()

    # Check the results
    assert len(results) == 2
    assert results[0].name == "test_name_1"
    assert results[0].content == "Test content 1"
    assert results[1].name == "test_name_2"
    assert results[1].content == "Test content 2"


@pytest.mark.asyncio
async def test_async_drop(mock_clickhouse):
    """Test async_drop method."""
    # Test when table exists
    with patch.object(mock_clickhouse, "async_exists", return_value=True):
        await mock_clickhouse.async_drop()

        # Verify command was called to drop table
        mock_clickhouse.async_client.command.assert_called_once()

    # Test when table doesn't exist
    with patch.object(mock_clickhouse, "async_exists", return_value=False):
        mock_clickhouse.async_client.command.reset_mock()
        await mock_clickhouse.async_drop()

        # Verify command was not called
        assert not mock_clickhouse.async_client.command.called


@pytest.mark.asyncio
async def test_async_exists(mock_clickhouse):
    """Test async_exists method."""
    # This just calls async_table_exists which we test elsewhere
    with patch.object(mock_clickhouse, "async_table_exists") as mock_async_table_exists:
        # Configure the mock to return a coroutine
        mock_async_table_exists.return_value = True

        assert await mock_clickhouse.async_exists() is True
