import json
from unittest.mock import MagicMock

import pytest

from agno.run import RunContext

MockSupermemory = MagicMock()


@pytest.fixture(scope="function")
def mock_client():
    mock = MagicMock()
    mock.reset_mock()

    # add() returns AddResponse with id and status
    add_response = MagicMock()
    add_response.model_dump.return_value = {"id": "doc-123", "status": "queued"}
    mock.add.return_value = add_response

    # search.memories() returns SearchMemoriesResponse
    search_result = MagicMock()
    search_result.model_dump.return_value = {
        "id": "mem-456",
        "memory": "User lives in NYC",
        "similarity": 0.92,
        "updated_at": "2025-01-01T00:00:00Z",
        "metadata": None,
        "chunk": None,
        "chunks": None,
        "context": None,
        "documents": None,
        "version": None,
    }
    search_response = MagicMock()
    search_response.results = [search_result]
    mock.search.memories.return_value = search_response

    # profile() returns ProfileResponse
    profile_response = MagicMock()
    profile_response.model_dump.return_value = {
        "profile": {
            "static": ["User is a software engineer"],
            "dynamic": ["User recently asked about Python"],
        },
        "search_results": None,
    }
    mock.profile.return_value = profile_response

    # memories.forget() returns MemoryForgetResponse
    forget_response = MagicMock()
    forget_response.model_dump.return_value = {"id": "mem-789", "forgotten": True}
    mock.memories.forget.return_value = forget_response

    return mock


@pytest.fixture(autouse=True)
def patch_supermemory(monkeypatch, mock_client):
    MockSupermemory.reset_mock()
    MockSupermemory.return_value = mock_client
    monkeypatch.setattr("agno.tools.supermemory.Supermemory", MockSupermemory)


@pytest.fixture
def toolkit():
    MockSupermemory.reset_mock()
    return _make_toolkit(api_key="fake-api-key")


@pytest.fixture
def dummy_run_context():
    return RunContext(run_id="test-run-id", session_id="test-session-id", user_id=None)


def _make_toolkit(**kwargs):
    from agno.tools.supermemory import SupermemoryTools

    return SupermemoryTools(**kwargs)


class TestSupermemoryToolkit:
    def test_init_with_api_key(self, toolkit, mock_client):
        assert toolkit is not None
        assert toolkit.client == mock_client
        MockSupermemory.assert_called_once_with(api_key="fake-api-key")

    def test_init_with_env_var(self, monkeypatch, mock_client):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "env-api-key")
        tk = _make_toolkit()
        assert tk.api_key == "env-api-key"
        MockSupermemory.assert_called_with(api_key="env-api-key")

    def test_init_with_custom_params(self, mock_client):
        tk = _make_toolkit(api_key="fake-key", search_limit=10, threshold=0.8)
        assert tk.search_limit == 10
        assert tk.threshold == 0.8

    def test_init_failure(self, monkeypatch):
        MockSupermemory.side_effect = Exception("Connection failed")
        with pytest.raises(ConnectionError, match="Failed to initialize Supermemory client"):
            _make_toolkit(api_key="bad-key")
        MockSupermemory.side_effect = None

    # -- User ID resolution --

    def test_get_user_id_from_constructor(self, toolkit, dummy_run_context):
        toolkit.user_id = "constructor_user"
        user_id = toolkit._get_user_id("test_method", dummy_run_context)
        assert user_id == "constructor_user"

    def test_get_user_id_from_run_context(self, toolkit):
        run_context = RunContext(run_id="test-run", session_id="test-session", user_id="context_user")
        user_id = toolkit._get_user_id("test_method", run_context)
        assert user_id == "context_user"

    def test_get_user_id_constructor_priority(self, toolkit):
        toolkit.user_id = "constructor_user"
        run_context = RunContext(run_id="test-run", session_id="test-session", user_id="context_user")
        user_id = toolkit._get_user_id("test_method", run_context)
        assert user_id == "constructor_user"

    def test_get_user_id_missing(self, toolkit, dummy_run_context):
        result = toolkit._get_user_id("test_method", dummy_run_context)
        assert "Error in test_method" in result

    # -- add_memory --

    def test_add_memory_success(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        result_str = toolkit.add_memory(dummy_run_context, content="I live in NYC")
        mock_client.add.assert_called_once_with(content="I live in NYC", container_tag="user-1")
        result = json.loads(result_str)
        assert result["id"] == "doc-123"
        assert result["status"] == "queued"

    def test_add_memory_with_metadata(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.add_memory(dummy_run_context, content="Test", metadata={"category": "personal"})
        mock_client.add.assert_called_once_with(
            content="Test", container_tag="user-1", metadata={"category": "personal"}
        )

    def test_add_memory_with_run_context_user_id(self, toolkit, mock_client):
        run_context = RunContext(run_id="test-run", session_id="test-session", user_id="ctx_user")
        toolkit.add_memory(run_context, content="Context test")
        mock_client.add.assert_called_once_with(content="Context test", container_tag="ctx_user")

    def test_add_memory_no_user_id(self, toolkit, dummy_run_context):
        result = toolkit.add_memory(dummy_run_context, content="No user")
        assert "Error in add_memory" in result

    def test_add_memory_error(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        mock_client.add.side_effect = Exception("API error")
        result = toolkit.add_memory(dummy_run_context, content="fail")
        assert "Error adding memory: API error" in result
        mock_client.add.side_effect = None

    # -- search_memory --

    def test_search_memory_success(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        result_str = toolkit.search_memory(dummy_run_context, query="where does the user live?")
        mock_client.search.memories.assert_called_once_with(
            q="where does the user live?", container_tag="user-1", limit=5
        )
        results = json.loads(result_str)
        assert len(results) == 1
        assert results[0]["memory"] == "User lives in NYC"

    def test_search_memory_with_custom_limit(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.search_memory(dummy_run_context, query="test", limit=10)
        mock_client.search.memories.assert_called_once_with(q="test", container_tag="user-1", limit=10)

    def test_search_memory_with_threshold(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.threshold = 0.7
        toolkit.search_memory(dummy_run_context, query="test")
        mock_client.search.memories.assert_called_once_with(q="test", container_tag="user-1", limit=5, threshold=0.7)

    def test_search_memory_no_user_id(self, toolkit, dummy_run_context):
        result = toolkit.search_memory(dummy_run_context, query="test")
        assert "Error in search_memory" in result

    def test_search_memory_error(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        mock_client.search.memories.side_effect = Exception("Search failed")
        result = toolkit.search_memory(dummy_run_context, query="fail")
        assert "Error searching memory: Search failed" in result
        mock_client.search.memories.side_effect = None

    # -- get_user_profile --

    def test_get_user_profile_success(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        result_str = toolkit.get_user_profile(dummy_run_context)
        mock_client.profile.assert_called_once_with(container_tag="user-1")
        result = json.loads(result_str)
        assert result["profile"]["static"] == ["User is a software engineer"]
        assert result["profile"]["dynamic"] == ["User recently asked about Python"]

    def test_get_user_profile_with_query(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.get_user_profile(dummy_run_context, query="food preferences")
        mock_client.profile.assert_called_once_with(container_tag="user-1", q="food preferences")

    def test_get_user_profile_with_threshold(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.threshold = 0.6
        toolkit.get_user_profile(dummy_run_context, query="test")
        mock_client.profile.assert_called_once_with(container_tag="user-1", q="test", threshold=0.6)

    def test_get_user_profile_no_user_id(self, toolkit, dummy_run_context):
        result = toolkit.get_user_profile(dummy_run_context)
        assert "Error in get_user_profile" in result

    def test_get_user_profile_error(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        mock_client.profile.side_effect = Exception("Profile error")
        result = toolkit.get_user_profile(dummy_run_context)
        assert "Error getting user profile: Profile error" in result
        mock_client.profile.side_effect = None

    # -- forget_memory --

    def test_forget_memory_by_id(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        result_str = toolkit.forget_memory(dummy_run_context, memory_id="mem-789")
        mock_client.memories.forget.assert_called_once_with(container_tag="user-1", id="mem-789")
        result = json.loads(result_str)
        assert result["forgotten"] is True

    def test_forget_memory_by_content(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.forget_memory(dummy_run_context, content="User lives in NYC")
        mock_client.memories.forget.assert_called_once_with(container_tag="user-1", content="User lives in NYC")

    def test_forget_memory_with_reason(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        toolkit.forget_memory(dummy_run_context, memory_id="mem-789", reason="outdated info")
        mock_client.memories.forget.assert_called_once_with(
            container_tag="user-1", id="mem-789", reason="outdated info"
        )

    def test_forget_memory_no_id_or_content(self, toolkit, dummy_run_context):
        toolkit.user_id = "user-1"
        result = toolkit.forget_memory(dummy_run_context)
        assert "Either memory_id or content must be provided" in result

    def test_forget_memory_no_user_id(self, toolkit, dummy_run_context):
        result = toolkit.forget_memory(dummy_run_context, memory_id="mem-789")
        assert "Error in forget_memory" in result

    def test_forget_memory_error(self, toolkit, mock_client, dummy_run_context):
        toolkit.user_id = "user-1"
        mock_client.memories.forget.side_effect = Exception("Forget failed")
        result = toolkit.forget_memory(dummy_run_context, memory_id="mem-789")
        assert "Error forgetting memory: Forget failed" in result
        mock_client.memories.forget.side_effect = None

    # -- enable/disable flags --

    def test_enable_flags_default(self, toolkit):
        function_names = list(toolkit.functions.keys())
        assert "add_memory" in function_names
        assert "search_memory" in function_names
        assert "get_user_profile" in function_names
        assert "forget_memory" in function_names

    def test_enable_flags_selective(self):
        tk = _make_toolkit(
            api_key="fake-key",
            enable_add_memory=True,
            enable_search_memory=False,
            enable_get_user_profile=False,
            enable_forget_memory=False,
        )
        function_names = list(tk.functions.keys())
        assert "add_memory" in function_names
        assert "search_memory" not in function_names
        assert "get_user_profile" not in function_names
        assert "forget_memory" not in function_names

    def test_enable_all_flag(self):
        tk = _make_toolkit(
            api_key="fake-key",
            enable_add_memory=False,
            enable_search_memory=False,
            enable_get_user_profile=False,
            enable_forget_memory=False,
            all=True,
        )
        function_names = list(tk.functions.keys())
        assert "add_memory" in function_names
        assert "search_memory" in function_names
        assert "get_user_profile" in function_names
        assert "forget_memory" in function_names
