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
    result = zep_tools.add_zep_message(role="user", content="test message")
    assert result == f"Message from 'user' added successfully to session {MOCK_SESSION_ID}."
    zep_tools.zep_client.thread.add_messages.assert_called_once()

    # Check that ZepMessage was created with correct parameters
    call_args = zep_tools.zep_client.thread.add_messages.call_args
    messages = call_args[1]["messages"]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "test message"


def test_add_zep_message_not_initialized():
    tools = ZepTools(api_key=MOCK_API_KEY)  # Don't initialize
    tools.zep_client = None  # Ensure client is None
    result = tools.add_zep_message(role="user", content="test message")
    assert result == "Error: Zep client/session not initialized."


def test_get_zep_memory_context(zep_tools):
    mock_memory = Mock()
    mock_memory.context = "test context"
    mock_memory.relevant_facts = None
    mock_memory.messages = None
    zep_tools.zep_client.thread.get_user_context.return_value = mock_memory

    result = zep_tools.get_zep_memory("context")
    assert result == "test context"
    zep_tools.zep_client.thread.get_user_context.assert_called_once()


def test_get_zep_memory_messages(zep_tools):
    mock_memory = Mock()
    mock_memory.messages = ["msg1", "msg2"]
    zep_tools.zep_client.thread.get.return_value = mock_memory

    result = zep_tools.get_zep_memory("messages")
    assert result == "['msg1', 'msg2']"


def test_get_zep_memory_unsupported_type(zep_tools):
    mock_memory = Mock()
    mock_memory.context = "fallback context"
    zep_tools.zep_client.thread.get_user_context.return_value = mock_memory

    result = zep_tools.get_zep_memory("unsupported")
    assert "Unsupported memory_type requested: unsupported" in result


def test_get_zep_memory_not_initialized():
    tools = ZepTools(api_key=MOCK_API_KEY)  # Don't initialize
    tools.zep_client = None  # Ensure client is None
    result = tools.get_zep_memory()
    assert result == "Error: Zep client/session not initialized."


def test_search_zep_memory_edges(zep_tools):
    # Setup mock search response for edges (facts)
    mock_edge1 = Mock()
    mock_edge1.fact = "User likes pizza"
    mock_edge2 = Mock()
    mock_edge2.fact = "User lives in NYC"

    mock_response = Mock()
    mock_response.edges = [mock_edge1, mock_edge2]
    mock_response.nodes = None

    zep_tools.zep_client.graph.search.return_value = mock_response

    result = zep_tools.search_zep_memory("test query", search_scope="edges")
    assert result == "Found 2 facts:\n- User likes pizza\n- User lives in NYC"
    zep_tools.zep_client.graph.search.assert_called_once_with(query="test query", user_id=MOCK_USER_ID, scope="edges")


def test_search_zep_memory_nodes(zep_tools):
    # Setup mock search response for nodes
    mock_node1 = Mock()
    mock_node1.name = "John"
    mock_node1.summary = "Software engineer"
    mock_node2 = Mock()
    mock_node2.name = "NYC"
    mock_node2.summary = "Major city in New York"

    mock_response = Mock()
    mock_response.edges = None
    mock_response.nodes = [mock_node1, mock_node2]

    zep_tools.zep_client.graph.search.return_value = mock_response

    result = zep_tools.search_zep_memory("test query", search_scope="nodes")
    assert result == "Found 2 nodes:\n- John: Software engineer\n- NYC: Major city in New York"
    zep_tools.zep_client.graph.search.assert_called_once_with(query="test query", user_id=MOCK_USER_ID, scope="nodes")


def test_search_zep_memory_no_results(zep_tools):
    mock_response = Mock()
    mock_response.edges = []
    mock_response.nodes = []

    zep_tools.zep_client.graph.search.return_value = mock_response
    result = zep_tools.search_zep_memory("test query")
    assert result == "No edges found for query: test query"


def test_search_zep_memory_not_initialized():
    tools = ZepTools(api_key=MOCK_API_KEY)  # Don't initialize
    tools.zep_client = None  # Ensure client is None
    result = tools.search_zep_memory("test query")
    assert result == "Error: Zep client/user not initialized."


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
    result = await async_zep_tools.add_zep_message(role="user", content="test message")
    assert result == f"Message from 'user' added successfully to session {MOCK_SESSION_ID}."
    async_zep_tools.zep_client.thread.add_messages.assert_called_once()

    # Check that ZepMessage was created with correct parameters
    call_args = async_zep_tools.zep_client.thread.add_messages.call_args
    messages = call_args[1]["messages"]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "test message"


@pytest.mark.asyncio
async def test_async_get_zep_memory(async_zep_tools):
    mock_memory = Mock()
    mock_memory.context = "test context"
    async_zep_tools.zep_client.thread.get_user_context.return_value = mock_memory

    result = await async_zep_tools.get_zep_memory()
    assert result == "test context"
    async_zep_tools.zep_client.thread.get_user_context.assert_called_once()


@pytest.mark.asyncio
async def test_async_search_zep_memory_edges(async_zep_tools):
    # Setup mock search response for edges (facts)
    mock_edge1 = Mock()
    mock_edge1.fact = "User likes pizza"
    mock_edge2 = Mock()
    mock_edge2.fact = "User lives in NYC"

    mock_response = Mock()
    mock_response.edges = [mock_edge1, mock_edge2]
    mock_response.nodes = None

    async_zep_tools.zep_client.graph.search.return_value = mock_response

    result = await async_zep_tools.search_zep_memory("test query", scope="edges")
    assert result == "Found 2 facts:\n- User likes pizza\n- User lives in NYC"
    async_zep_tools.zep_client.graph.search.assert_called_once_with(
        query="test query", user_id=MOCK_USER_ID, scope="edges", limit=5
    )
