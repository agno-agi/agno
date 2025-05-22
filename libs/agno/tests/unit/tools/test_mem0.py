import json
from unittest.mock import MagicMock

import pytest

from agno.tools.mem0 import Mem0Tools

MockMemory = MagicMock()
MockMemoryClient = MagicMock()


@pytest.fixture(scope="function")
def mock_memory_instance():
    mock = MockMemory()
    mock.reset_mock()
    mock.add.return_value = {"results": [{"id": "mem-add-123", "memory": "added memory", "event": "ADD"}]}
    mock.search.return_value = {"results": [{"id": "mem-search-456", "memory": "found memory", "score": 0.9}]}
    mock.get.return_value = {"id": "mem-get-789", "memory": "specific memory"}
    mock.update.return_value = {"message": "Memory updated successfully!"}
    mock.delete.return_value = None
    mock.get_all.return_value = {"results": [{"id": "mem-all-1", "memory": "all mem 1"}]}
    mock.delete_all.return_value = None
    mock.history.return_value = [{"event": "ADD", "memory_id": "hist-1"}]
    return mock


@pytest.fixture(scope="function")
def mock_memory_client_instance():
    mock = MockMemoryClient()
    mock.reset_mock()
    mock.add.return_value = [{"id": "mem-client-add-123", "memory": "added client memory", "event": "ADD"}]
    mock.search.return_value = [{"id": "mem-client-search-456", "memory": "found client memory", "score": 0.8}]
    mock.get.return_value = {"id": "mem-client-get-789", "memory": "specific client memory"}
    mock.update.return_value = {"message": "Client memory updated successfully!"}
    mock.delete.return_value = None
    mock.get_all.return_value = [{"id": "mem-client-all-1", "memory": "all client mem 1"}]
    mock.delete_all.return_value = None
    mock.history.return_value = [{"event": "ADD", "memory_id": "client-hist-1"}]
    return mock


@pytest.fixture(autouse=True)
def patch_mem0_library(monkeypatch, mock_memory_instance, mock_memory_client_instance):
    monkeypatch.setattr("agno.tools.mem0.Memory", MockMemory)
    monkeypatch.setattr("agno.tools.mem0.MemoryClient", MockMemoryClient)
    MockMemory.from_config.return_value = mock_memory_instance
    MockMemoryClient.return_value = mock_memory_client_instance


@pytest.fixture
def toolkit_config(monkeypatch):
    # Reset the class mock's config call count before creating instance
    MockMemory.from_config.reset_mock()
    MockMemoryClient.reset_mock()  # Also reset client mock
    monkeypatch.delenv("MEM0_API_KEY", raising=False)  # raising=False avoids error if var doesn't exist
    toolkit = Mem0Tools(config={}, user_id=None)

    return toolkit


@pytest.fixture
def toolkit_api_key():
    MockMemoryClient.reset_mock()
    MockMemory.from_config.reset_mock()
    return Mem0Tools(api_key="fake-api-key")


@pytest.fixture
def dummy_agent():
    """Return a minimal Agent-like mock object the toolkit expects."""
    agent = MagicMock()
    agent.session_state = {}
    return agent


class TestMem0Toolkit:
    def test_init_with_config(self, toolkit_config, mock_memory_instance):
        assert toolkit_config is not None

        # Check the *instance* of client is the mock returned by Memory.from_config
        assert isinstance(toolkit_config.client, MagicMock)
        assert toolkit_config.client == mock_memory_instance  # Check it's the correct mock

        # Check the CLASS method MockMemory.from_config was called once
        MockMemory.from_config.assert_called_once_with({})

        MockMemoryClient.assert_not_called()

    def test_init_with_api_key(self, toolkit_api_key, mock_memory_client_instance):
        assert toolkit_api_key is not None
        assert isinstance(toolkit_api_key.client, MagicMock)
        assert toolkit_api_key.client == mock_memory_client_instance
        MockMemoryClient.assert_called_once_with(api_key="fake-api-key")
        MockMemory.from_config.assert_not_called()

    def test_get_user_id_from_arg(self, toolkit_config):
        toolkit_config.user_id = "arg_user"
        user_id = toolkit_config._get_user_id("test_method", agent=None)
        assert user_id == "arg_user"

    def test_get_user_id_no_id_provided(self, toolkit_config, dummy_agent):
        result = toolkit_config._get_user_id("test_method", agent=dummy_agent)
        assert result == "Error in test_method: A user_id must be provided in the method call."

    def test_add_memory_success_arg_id(self, toolkit_config, mock_memory_instance, dummy_agent):
        toolkit_config.user_id = "test_user_add"
        result_str = toolkit_config.add_memory(dummy_agent, content="Test message")
        mock_memory_instance.add.assert_called_once_with(
            [{"role": "user", "content": "Test message"}],
            user_id="test_user_add",
        )
        expected_result = {"results": [{"id": "mem-add-123", "memory": "added memory", "event": "ADD"}]}
        assert json.loads(result_str) == expected_result

    def test_add_memory_dict_message(self, toolkit_config, mock_memory_instance, dummy_agent):
        toolkit_config.user_id = "user1"
        dict_content = {"role": "user", "content": "Dict message"}
        result_str = toolkit_config.add_memory(dummy_agent, content=dict_content)
        mock_memory_instance.add.assert_called_once_with(
            [{"role": "user", "content": json.dumps(dict_content)}],
            user_id="user1",
        )
        expected_result = {"results": [{"id": "mem-add-123", "memory": "added memory", "event": "ADD"}]}
        assert json.loads(result_str) == expected_result

    def test_add_memory_invalid_message_type(self, toolkit_config, mock_memory_instance, dummy_agent):
        toolkit_config.user_id = "user1"
        result_str = toolkit_config.add_memory(dummy_agent, content=123)
        mock_memory_instance.add.assert_called_once_with(
            [{"role": "user", "content": "123"}],
            user_id="user1",
        )
        expected_result = {"results": [{"id": "mem-add-123", "memory": "added memory", "event": "ADD"}]}
        assert json.loads(result_str) == expected_result

    def test_add_memory_no_user_id(self, toolkit_config, dummy_agent):
        result = toolkit_config.add_memory(dummy_agent, content="No user ID test")
        expected_error_msg = "Error in add_memory: A user_id must be provided in the method call."
        assert expected_error_msg in result

    def test_search_memory_success_arg_id(self, toolkit_config, mock_memory_instance, dummy_agent):
        toolkit_config.user_id = "test_user_search"
        result_str = toolkit_config.search_memory(dummy_agent, query="find stuff")
        mock_memory_instance.search.assert_called_once_with(query="find stuff", user_id="test_user_search")
        expected_result = [{"id": "mem-search-456", "memory": "found memory", "score": 0.9}]
        assert json.loads(result_str) == expected_result

    def test_search_memory_success_default_call(self, toolkit_config, mock_memory_instance, dummy_agent):
        toolkit_config.user_id = "user_default"
        toolkit_config.search_memory(dummy_agent, query="default search")
        mock_memory_instance.search.assert_called_once_with(query="default search", user_id="user_default")

    def test_search_memory_no_user_id(self, toolkit_config, dummy_agent):
        result = toolkit_config.search_memory(dummy_agent, query="No user ID search")
        expected_error_msg = "Error in search_memory: A user_id must be provided in the method call."
        assert result == expected_error_msg

    def test_search_memory_api_key_list_return(self, toolkit_api_key, mock_memory_client_instance, dummy_agent):
        toolkit_api_key.user_id = "default_user_api"
        result_str = toolkit_api_key.search_memory(dummy_agent, query="client search")
        mock_memory_client_instance.search.assert_called_once_with(query="client search", user_id="default_user_api")
        expected_result = [{"id": "mem-client-search-456", "memory": "found client memory", "score": 0.8}]
        assert json.loads(result_str) == expected_result

    def test_get_all_memories_success(self, toolkit_api_key, mock_memory_client_instance, dummy_agent):
        toolkit_api_key.user_id = "user-all-1"
        result_str = toolkit_api_key.get_all_memories(dummy_agent)
        mock_memory_client_instance.get_all.assert_called_once_with(user_id="user-all-1")
        expected = [{"id": "mem-client-all-1", "memory": "all client mem 1"}]
        assert json.loads(result_str) == expected

    def test_get_all_memories_success_dict_return(self, toolkit_config, mock_memory_instance, dummy_agent):
        toolkit_config.user_id = "user-all-dict"
        result_str = toolkit_config.get_all_memories(dummy_agent)
        mock_memory_instance.get_all.assert_called_once_with(user_id="user-all-dict")
        expected = [{"id": "mem-all-1", "memory": "all mem 1"}]
        assert json.loads(result_str) == expected

    def test_get_all_memories_no_user_id(self, toolkit_api_key, dummy_agent):
        result_str = toolkit_api_key.get_all_memories(dummy_agent)
        expected_error_msg = "Error in get_all_memories: A user_id must be provided in the method call."
        assert result_str == expected_error_msg

    def test_get_all_memories_error(self, toolkit_api_key, mock_memory_client_instance, dummy_agent):
        toolkit_api_key.user_id = "error-user"
        mock_memory_client_instance.get_all.side_effect = Exception("Test get_all error")
        result_str = toolkit_api_key.get_all_memories(dummy_agent)
        assert "Error getting all memories: Test get_all error" in result_str

    def test_delete_all_memories_success(self, toolkit_api_key, mock_memory_client_instance, dummy_agent):
        toolkit_api_key.user_id = "user-delete-all-1"
        result_str = toolkit_api_key.delete_all_memories(dummy_agent)
        mock_memory_client_instance.delete_all.assert_called_once_with(user_id="user-delete-all-1")
        expected_str = "Successfully deleted all memories for user_id: user-delete-all-1."
        assert result_str == expected_str

    def test_delete_all_memories_no_user_id(self, toolkit_api_key, dummy_agent):
        result_str = toolkit_api_key.delete_all_memories(dummy_agent)
        expected_error_msg = "Error in delete_all_memories: A user_id must be provided in the method call."
        assert "Error deleting all memories:" in result_str and expected_error_msg in result_str

    def test_delete_all_memories_error(self, toolkit_api_key, mock_memory_client_instance, dummy_agent):
        toolkit_api_key.user_id = "error-user"
        mock_memory_client_instance.delete_all.side_effect = Exception("Test delete_all error")
        result_str = toolkit_api_key.delete_all_memories(dummy_agent)
        assert "Error deleting all memories: Test delete_all error" in result_str
