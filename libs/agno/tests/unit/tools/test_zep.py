from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.tools.zep import ZepAsyncTools, ZepTools

# Test data
MOCK_API_KEY = "test_api_key"
MOCK_SESSION_ID = "test-session"
MOCK_USER_ID = "test-user"


@pytest.fixture
def mock_zep():
    with patch("agno.tools.zep.Zep") as mock:
        yield mock


@pytest.fixture
def zep_tools(mock_zep, monkeypatch):
    # Setup environment
    monkeypatch.setenv("ZEP_API_KEY", MOCK_API_KEY)

    # Create and configure mock instance
    mock_instance = Mock()
    mock_instance.user = Mock()
    mock_instance.memory = Mock()
    mock_instance.graph = Mock()
    mock_zep.return_value = mock_instance

    # Create tools instance
    tools = ZepTools(session_id=MOCK_SESSION_ID, user_id=MOCK_USER_ID)
    tools.initialize()
    return tools


def test_initialization(zep_tools):
    assert zep_tools._initialized
    assert zep_tools.session_id == MOCK_SESSION_ID
    assert zep_tools.user_id == MOCK_USER_ID


def test_initialization_no_api_key(monkeypatch):
    monkeypatch.delenv("ZEP_API_KEY", raising=False)
    with pytest.raises(ValueError, match="No Zep API key provided"):
        ZepTools()


def test_add_zep_message(zep_tools):
    result = zep_tools.add_zep_message("user", "test message")
    assert result == f"Message from 'user' added successfully to session {MOCK_SESSION_ID}."
    zep_tools.zep_client.memory.add.assert_called_once()

    # Check that ZepMessage was created with correct parameters
    call_args = zep_tools.zep_client.memory.add.call_args
    messages = call_args[1]["messages"]
    assert len(messages) == 1
    assert messages[0].role_type == "user"
    assert messages[0].content == "test message"


def test_add_zep_message_not_initialized():
    tools = ZepTools(api_key=MOCK_API_KEY)  # Don't initialize
    result = tools.add_zep_message("user", "test message")
    assert result == "Error: Zep client/session not initialized."


def test_get_zep_memory_context(zep_tools):
    mock_memory = Mock()
    mock_memory.context = "test context"
    zep_tools.zep_client.memory.get.return_value = mock_memory

    result = zep_tools.get_zep_memory("context")
    assert result == "test context"
    zep_tools.zep_client.memory.get.assert_called_once()


def test_get_zep_memory_summary(zep_tools):
    mock_memory = Mock()
    mock_memory.summary = Mock(content="test summary")
    zep_tools.zep_client.memory.get.return_value = mock_memory

    result = zep_tools.get_zep_memory("summary")
    assert result == "test summary"


def test_get_zep_memory_not_initialized():
    tools = ZepTools(api_key=MOCK_API_KEY)  # Don't initialize
    result = tools.get_zep_memory()
    assert result == "Error: Zep client/session not initialized."


def test_search_zep_memory(zep_tools):
    # Setup mock search response
    mock_message = Mock()
    mock_message.content = "test content"
    mock_message.created_at = "2024-01-01"
    mock_message.uuid_ = "123"

    mock_response = Mock()
    mock_response.message = mock_message
    mock_response.score = 0.9

    zep_tools.zep_client.memory.search.return_value = [mock_response]

    result = zep_tools.search_zep_memory("test query")
    assert result == "test content"
    zep_tools.zep_client.memory.search.assert_called_once_with(
        text="test query", session_id=MOCK_SESSION_ID, search_scope="messages"
    )


def test_search_zep_memory_no_results(zep_tools):
    zep_tools.zep_client.memory.search.return_value = []
    result = zep_tools.search_zep_memory("test query")
    assert result == "No relevant messages found."


def test_search_zep_memory_not_initialized():
    tools = ZepTools(api_key=MOCK_API_KEY)  # Don't initialize
    result = tools.search_zep_memory("test query")
    assert result == "Error: Zep client/user/session not initialized."


# Async Tests
@pytest.fixture
def mock_async_zep():
    with patch("agno.tools.zep.AsyncZep") as mock:
        yield mock


@pytest.fixture
async def async_zep_tools(mock_async_zep, monkeypatch):
    monkeypatch.setenv("ZEP_API_KEY", MOCK_API_KEY)

    # Create and configure mock instance
    mock_instance = AsyncMock()
    mock_instance.user = AsyncMock()
    mock_instance.memory = AsyncMock()
    mock_instance.graph = AsyncMock()
    mock_async_zep.return_value = mock_instance

    # Create tools instance
    tools = ZepAsyncTools(session_id=MOCK_SESSION_ID, user_id=MOCK_USER_ID)
    await tools.initialize()
    return tools


@pytest.mark.asyncio
async def test_async_initialization(async_zep_tools):
    assert async_zep_tools._initialized
    assert async_zep_tools.session_id == MOCK_SESSION_ID
    assert async_zep_tools.user_id == MOCK_USER_ID


@pytest.mark.asyncio
async def test_async_add_zep_message(async_zep_tools):
    result = await async_zep_tools.add_zep_message("user", "test message")
    assert result == f"Message from 'user' added successfully to session {MOCK_SESSION_ID}."
    async_zep_tools.zep_client.memory.add.assert_called_once()

    # Check that ZepMessage was created with correct parameters
    call_args = async_zep_tools.zep_client.memory.add.call_args
    messages = call_args[1]["messages"]
    assert len(messages) == 1
    assert messages[0].role_type == "user"
    assert messages[0].content == "test message"


@pytest.mark.asyncio
async def test_async_get_zep_memory(async_zep_tools):
    mock_memory = Mock()
    mock_memory.context = "test context"
    async_zep_tools.zep_client.memory.get.return_value = mock_memory

    result = await async_zep_tools.get_zep_memory()
    assert result == "test context"
    async_zep_tools.zep_client.memory.get.assert_called_once()


@pytest.mark.asyncio
async def test_async_search_zep_memory(async_zep_tools):
    mock_message = Mock()
    mock_message.content = "test content"
    mock_message.created_at = "2024-01-01"
    mock_message.uuid_ = "123"

    mock_response = Mock()
    mock_response.message = mock_message
    mock_response.score = 0.9

    async_zep_tools.zep_client.memory.search.return_value = [mock_response]

    result = await async_zep_tools.search_zep_memory("test query")
    assert result == "test content"
    async_zep_tools.zep_client.memory.search.assert_called_once_with(
        text="test query", session_id=MOCK_SESSION_ID, search_scope="messages"
    )
