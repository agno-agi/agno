import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.memori import MemoriTools, create_memori_search_tool

MockMemori = MagicMock()
MockCreateMemoryTool = MagicMock()


@pytest.fixture(scope="function")
def mock_memori_instance():
    mock = MagicMock()
    mock.enable.return_value = None
    mock.disable.return_value = None
    mock.record_conversation.return_value = None
    mock.get_memory_stats.return_value = {
        "total_memories": 15,
        "memories_by_retention": {"short_term": 3, "long_term": 12},
        "database_type": "sqlite",
    }
    mock._enabled = True
    return mock


@pytest.fixture(scope="function")
def mock_memory_tool_instance():
    mock = MagicMock()
    mock.execute.return_value = [
        {"content": "User prefers Python over JavaScript", "score": 0.95},
        {"content": "User is working on an e-commerce project", "score": 0.88},
    ]
    return mock


@pytest.fixture(autouse=True)
def patch_memori_library(monkeypatch, mock_memori_instance, mock_memory_tool_instance):
    monkeypatch.setattr("agno.tools.memori.Memori", MockMemori)
    monkeypatch.setattr("agno.tools.memori.create_memory_tool", MockCreateMemoryTool)
    MockMemori.return_value = mock_memori_instance
    MockCreateMemoryTool.return_value = mock_memory_tool_instance


@pytest.fixture
def memori_toolkit_default(mock_memori_instance, mock_memory_tool_instance):
    """Create MemoriTools with default configuration."""
    toolkit = MemoriTools()
    return toolkit


@pytest.fixture
def memori_toolkit_custom(mock_memori_instance, mock_memory_tool_instance):
    """Create MemoriTools with custom configuration."""
    MockMemori.reset_mock()
    MockCreateMemoryTool.reset_mock()
    toolkit = MemoriTools(
        database_connect="postgresql://user:pass@localhost/memori_test",
        namespace="test_namespace",
        conscious_ingest=False,
        auto_ingest=False,
        verbose=True,
        config={"custom_key": "custom_value"},
        auto_enable=False,
    )
    return toolkit


@pytest.fixture
def dummy_agent():
    """Return a minimal Agent-like mock object with message capabilities."""
    agent = MagicMock()
    agent.session_state = {}

    # Mock messages for session
    messages = [
        MagicMock(role="user", content="Hello, I'm John"),
        MagicMock(role="assistant", content="Hello John! Nice to meet you."),
        MagicMock(role="user", content="I like Python programming"),
        MagicMock(role="assistant", content="That's great! Python is a wonderful language."),
    ]

    # Mock get_messages_for_session method
    agent.get_messages_for_session.return_value = messages

    # Mock memory with messages
    agent.memory = MagicMock()
    agent.memory.messages = messages

    # Mock run_response
    agent.run_response = MagicMock()
    agent.run_response.content = "That's great! Python is a wonderful language."
    agent.run_response.get_content_as_string.return_value = "That's great! Python is a wonderful language."

    return agent


class TestMemoriTools:
    def test_init_default_config(self, memori_toolkit_default, mock_memori_instance, mock_memory_tool_instance):
        """Test initialization with default configuration."""
        assert memori_toolkit_default is not None
        assert memori_toolkit_default.database_connect == "sqlite:///agno_memori_memory.db"
        assert memori_toolkit_default.namespace == "agno_default"
        assert memori_toolkit_default.conscious_ingest is True
        assert memori_toolkit_default.auto_ingest is True
        assert memori_toolkit_default.verbose is False
        assert memori_toolkit_default.config == {}

        # Check that Memori was initialized with correct parameters
        MockMemori.assert_called_once_with(
            database_connect="sqlite:///agno_memori_memory.db",
            conscious_ingest=True,
            auto_ingest=True,
            verbose=False,
            namespace="agno_default",
        )

        # Check that memory system was enabled
        mock_memori_instance.enable.assert_called_once()

        # Check that memory tool was created
        MockCreateMemoryTool.assert_called_once_with(mock_memori_instance)

    def test_init_custom_config(self, memori_toolkit_custom, mock_memori_instance, mock_memory_tool_instance):
        """Test initialization with custom configuration."""
        assert memori_toolkit_custom.database_connect == "postgresql://user:pass@localhost/memori_test"
        assert memori_toolkit_custom.namespace == "test_namespace"
        assert memori_toolkit_custom.conscious_ingest is False
        assert memori_toolkit_custom.auto_ingest is False
        assert memori_toolkit_custom.verbose is True
        assert memori_toolkit_custom.config == {"custom_key": "custom_value"}

        # Check that Memori was initialized with custom parameters
        MockMemori.assert_called_once_with(
            database_connect="postgresql://user:pass@localhost/memori_test",
            conscious_ingest=False,
            auto_ingest=False,
            verbose=True,
            namespace="test_namespace",
            custom_key="custom_value",
        )

        # Check that memory system was NOT enabled due to auto_enable=False
        mock_memori_instance.enable.assert_not_called()

    def test_init_with_connection_error(self, monkeypatch):
        """Test initialization failure with connection error."""

        def mock_memori_init(*args, **kwargs):
            raise Exception("Database connection failed")

        monkeypatch.setattr("agno.tools.memori.Memori", mock_memori_init)

        with pytest.raises(ConnectionError, match="Failed to initialize Memori memory system"):
            MemoriTools()

    def test_search_memory_success(self, memori_toolkit_default, mock_memory_tool_instance, dummy_agent):
        """Test successful memory search."""
        result_str = memori_toolkit_default.search_memory(dummy_agent, "Python programming")

        # Check that memory tool execute was called
        mock_memory_tool_instance.execute.assert_called_once_with(query="Python programming")

        # Parse and validate result
        result = json.loads(result_str)
        assert result["success"] is True
        assert result["query"] == "Python programming"
        assert result["count"] == 2
        assert len(result["results"]) == 2
        assert result["results"][0]["content"] == "User prefers Python over JavaScript"
        assert result["results"][0]["score"] == 0.95

    def test_search_memory_with_limit(self, memori_toolkit_default, mock_memory_tool_instance, dummy_agent):
        """Test memory search with limit parameter."""
        result_str = memori_toolkit_default.search_memory(dummy_agent, "Python", limit=1)

        mock_memory_tool_instance.execute.assert_called_once_with(query="Python")

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["results"]) == 1

    def test_search_memory_empty_query(self, memori_toolkit_default, dummy_agent):
        """Test memory search with empty query."""
        result_str = memori_toolkit_default.search_memory(dummy_agent, "   ")

        result = json.loads(result_str)
        assert "error" in result
        assert result["error"] == "Please provide a search query"

    def test_search_memory_no_results(self, memori_toolkit_default, mock_memory_tool_instance, dummy_agent):
        """Test memory search with no results."""
        mock_memory_tool_instance.execute.return_value = None

        result_str = memori_toolkit_default.search_memory(dummy_agent, "nonexistent query")

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["count"] == 0
        assert result["results"] == []
        assert result["message"] == "No relevant memories found"

    def test_search_memory_exception(self, memori_toolkit_default, mock_memory_tool_instance, dummy_agent):
        """Test memory search with exception."""
        mock_memory_tool_instance.execute.side_effect = Exception("Search failed")

        result_str = memori_toolkit_default.search_memory(dummy_agent, "test query")

        result = json.loads(result_str)
        assert result["success"] is False
        assert "Memory search error: Search failed" in result["error"]

    def test_record_conversation_success_with_session_messages(
        self, memori_toolkit_default, mock_memori_instance, dummy_agent
    ):
        """Test successful conversation recording using session messages."""
        result_str = memori_toolkit_default.record_conversation(dummy_agent, "User likes Python")

        # Check that record_conversation was called with the content directly
        mock_memori_instance.record_conversation.assert_called_once_with(
            user_input="User likes Python", ai_output="I've noted this information and will remember it."
        )

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["message"] == "Memory added successfully via conversation recording"
        assert result["content_length"] == len("User likes Python")

    def test_record_conversation_success_with_memory_messages(
        self, memori_toolkit_default, mock_memori_instance, dummy_agent
    ):
        """Test conversation recording using memory messages when session messages fail."""
        # Remove get_messages_for_session to test fallback
        del dummy_agent.get_messages_for_session

        result_str = memori_toolkit_default.record_conversation(dummy_agent, "User prefers JavaScript")

        # Should extract from memory.messages
        mock_memori_instance.record_conversation.assert_called_once_with(
            user_input="User prefers JavaScript", ai_output="I've noted this information and will remember it."
        )

        result = json.loads(result_str)
        assert result["success"] is True

    def test_record_conversation_success_with_run_response_fallback(
        self, memori_toolkit_default, mock_memori_instance, dummy_agent
    ):
        """Test conversation recording using run_response as fallback."""
        # Remove other methods to test run_response fallback
        del dummy_agent.get_messages_for_session
        dummy_agent.memory.messages = []

        memori_toolkit_default.record_conversation(dummy_agent, "Test content")

        # Should extract from run_response.content
        mock_memori_instance.record_conversation.assert_called_once_with(
            user_input="Test content", ai_output="I've noted this information and will remember it."
        )

    def test_record_conversation_with_default_fallback(self, memori_toolkit_default, mock_memori_instance, dummy_agent):
        """Test conversation recording with default AI response fallback."""
        # Remove all methods to test default fallback
        del dummy_agent.get_messages_for_session
        dummy_agent.memory.messages = []
        dummy_agent.run_response = None

        memori_toolkit_default.record_conversation(dummy_agent, "Test content")

        # Should use default AI response
        mock_memori_instance.record_conversation.assert_called_once_with(
            user_input="Test content", ai_output="I've noted this information and will remember it."
        )

    def test_record_conversation_empty_content(self, memori_toolkit_default, dummy_agent):
        """Test record conversation with empty content."""
        result_str = memori_toolkit_default.record_conversation(dummy_agent, "   ")

        result = json.loads(result_str)
        assert result["success"] is False
        assert result["error"] == "Content cannot be empty"

    def test_record_conversation_exception(self, memori_toolkit_default, mock_memori_instance, dummy_agent):
        """Test record conversation with exception."""
        mock_memori_instance.record_conversation.side_effect = Exception("Recording failed")

        result_str = memori_toolkit_default.record_conversation(dummy_agent, "Test content")

        result = json.loads(result_str)
        assert result["success"] is False
        assert "Failed to add memory: Recording failed" in result["error"]

    def test_get_memory_stats_success(self, memori_toolkit_default, mock_memori_instance, dummy_agent):
        """Test successful memory stats retrieval."""
        result_str = memori_toolkit_default.get_memory_stats(dummy_agent)

        # Check that get_memory_stats was called
        mock_memori_instance.get_memory_stats.assert_called_once()

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["namespace"] == "agno_default"
        assert result["database_connect"] == "sqlite:///agno_memori_memory.db"
        assert result["conscious_ingest"] is True
        assert result["auto_ingest"] is True
        assert result["verbose"] is False
        assert result["memory_system_enabled"] is True
        assert result["total_memories"] == 15
        assert result["short_term_memories"] == 3
        assert result["long_term_memories"] == 12

    def test_get_memory_stats_no_method(self, memori_toolkit_default, mock_memori_instance, dummy_agent):
        """Test memory stats when get_memory_stats method doesn't exist."""
        del mock_memori_instance.get_memory_stats

        result_str = memori_toolkit_default.get_memory_stats(dummy_agent)

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["total_memories"] == 0
        assert result["short_term_memories"] == 0
        assert result["long_term_memories"] == 0

    def test_get_memory_stats_method_exception(self, memori_toolkit_default, mock_memori_instance, dummy_agent):
        """Test memory stats when get_memory_stats method raises exception."""
        mock_memori_instance.get_memory_stats.side_effect = Exception("Stats failed")

        result_str = memori_toolkit_default.get_memory_stats(dummy_agent)

        result = json.loads(result_str)
        assert result["success"] is True
        assert result["total_memories"] == 0
        assert result["stats_warning"] == "Detailed memory statistics not available"

    def test_get_memory_stats_general_exception(self, memori_toolkit_default, mock_memori_instance, dummy_agent):
        """Test memory stats with general exception."""
        # Make the entire method fail
        mock_memori_instance._enabled = None  # This will cause hasattr check to fail

        with patch("agno.tools.memori.hasattr", side_effect=Exception("General error")):
            result_str = memori_toolkit_default.get_memory_stats(dummy_agent)

        result = json.loads(result_str)
        assert result["success"] is False
        assert "Failed to get memory statistics: General error" in result["error"]

    def test_enable_memory_system_success(self, memori_toolkit_default, mock_memori_instance):
        """Test successful memory system enable."""
        result = memori_toolkit_default.enable_memory_system()

        assert result is True
        mock_memori_instance.enable.assert_called()

    def test_enable_memory_system_exception(self, memori_toolkit_default, mock_memori_instance):
        """Test memory system enable with exception."""
        mock_memori_instance.enable.side_effect = Exception("Enable failed")

        result = memori_toolkit_default.enable_memory_system()

        assert result is False

    def test_disable_memory_system_success(self, memori_toolkit_default, mock_memori_instance):
        """Test successful memory system disable."""
        result = memori_toolkit_default.disable_memory_system()

        assert result is True
        mock_memori_instance.disable.assert_called_once()

    def test_disable_memory_system_no_method(self, memori_toolkit_default, mock_memori_instance):
        """Test memory system disable when method doesn't exist."""
        del mock_memori_instance.disable

        result = memori_toolkit_default.disable_memory_system()

        assert result is False

    def test_disable_memory_system_exception(self, memori_toolkit_default, mock_memori_instance):
        """Test memory system disable with exception."""
        mock_memori_instance.disable.side_effect = Exception("Disable failed")

        result = memori_toolkit_default.disable_memory_system()

        assert result is False

    def test_toolkit_tools_registration(self, memori_toolkit_default):
        """Test that all tools are properly registered."""
        tools = memori_toolkit_default.tools
        tool_names = [tool.__name__ for tool in tools]

        assert "search_memory" in tool_names
        assert "record_conversation" in tool_names
        assert "get_memory_stats" in tool_names
        assert len(tools) == 3


class TestCreateMemoriSearchTool:
    def test_create_memori_search_tool(self, memori_toolkit_default, mock_memory_tool_instance):
        """Test creating a standalone memory search tool."""
        search_tool = create_memori_search_tool(memori_toolkit_default)

        assert callable(search_tool)

        # Test the created tool
        result = search_tool("test query")
        mock_memory_tool_instance.execute.assert_called_once_with(query="test query")

        # Should return string representation of results
        expected_results = [
            {"content": "User prefers Python over JavaScript", "score": 0.95},
            {"content": "User is working on an e-commerce project", "score": 0.88},
        ]
        assert str(expected_results) in result

    def test_create_memori_search_tool_empty_query(self, memori_toolkit_default):
        """Test standalone search tool with empty query."""
        search_tool = create_memori_search_tool(memori_toolkit_default)

        result = search_tool("   ")
        assert result == "Please provide a search query"

    def test_create_memori_search_tool_no_results(self, memori_toolkit_default, mock_memory_tool_instance):
        """Test standalone search tool with no results."""
        mock_memory_tool_instance.execute.return_value = None
        search_tool = create_memori_search_tool(memori_toolkit_default)

        result = search_tool("nonexistent")
        assert result == "No relevant memories found"

    def test_create_memori_search_tool_exception(self, memori_toolkit_default, mock_memory_tool_instance):
        """Test standalone search tool with exception."""
        mock_memory_tool_instance.execute.side_effect = Exception("Search error")
        search_tool = create_memori_search_tool(memori_toolkit_default)

        result = search_tool("test")
        assert "Memory search error: Search error" in result
