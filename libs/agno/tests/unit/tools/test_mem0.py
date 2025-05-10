import json
from unittest.mock import MagicMock

import pytest

from agno.tools.mem0 import Mem0Toolkit

MockMemory = MagicMock()
MockMemoryClient = MagicMock()


@pytest.fixture(scope="function")
def mock_memory_instance():
    # Reset mock before each test using it
    mock = MockMemory()
    # Reset call counts etc. for function scope
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
    # Reset mock before each test using it
    mock = MockMemoryClient()
    # Reset call counts etc. for function scope
    mock.reset_mock()
    # MemoryClient methods might return lists directly or slightly different structures
    mock.add.return_value = [{"id": "mem-client-add-123", "memory": "added client memory", "event": "ADD"}]
    # Adjusted return value to be a list as expected by toolkit logic
    mock.search.return_value = [{"id": "mem-client-search-456", "memory": "found client memory", "score": 0.8}]
    mock.get.return_value = {"id": "mem-client-get-789", "memory": "specific client memory"}
    mock.update.return_value = {"message": "Client memory updated successfully!"}
    mock.delete.return_value = None
    mock.get_all.return_value = [{"id": "mem-client-all-1", "memory": "all client mem 1"}]
    mock.delete_all.return_value = None
    mock.history.return_value = [{"event": "ADD", "memory_id": "client-hist-1"}]
    return mock


# Patch the mem0 library classes for all tests in this module
@pytest.fixture(autouse=True)
def patch_mem0_library(monkeypatch, mock_memory_instance, mock_memory_client_instance):
    # Mock the classes themselves to control instantiation
    monkeypatch.setattr("agno.tools.mem0.Memory", MockMemory)
    monkeypatch.setattr("agno.tools.mem0.MemoryClient", MockMemoryClient)
    # Point the static/class method `from_config` to return our instance
    MockMemory.from_config.return_value = mock_memory_instance  # Used if config is provided and API key is not
    # Point the constructor of MemoryClient to return our instance
    # This covers both API key and default initialization
    MockMemoryClient.return_value = mock_memory_client_instance

    # Ensure getenv doesn't interfere with testing config path
    # Patch getenv within the module under test's namespace
    # monkeypatch.setattr("agno.tools.mem0.getenv", lambda key, default=None: None) # REMOVED


@pytest.fixture
def toolkit_config(monkeypatch):
    # Reset the class mock's config call count before creating instance
    MockMemory.from_config.reset_mock()
    MockMemoryClient.reset_mock()  # Also reset client mock

    # Delete the environment variable JUST before creating the instance
    monkeypatch.delenv("MEM0_API_KEY", raising=False)  # raising=False avoids error if var doesn't exist

    # Toolkit initialized with config (should use Memory.from_config)
    toolkit = Mem0Toolkit(config={})  # No default user_id

    return toolkit


@pytest.fixture
def toolkit_api_key():
    # Reset the class mock's call count before creating instance
    MockMemoryClient.reset_mock()
    MockMemory.from_config.reset_mock()  # Also reset memory mock
    # Toolkit initialized with API key (uses MemoryClient)
    return Mem0Toolkit(api_key="fake-api-key")  # No default user_id


# --- Test Class ---


class TestMem0Toolkit:
    # -- Initialization Tests --
    def test_init_with_config(self, toolkit_config, mock_memory_instance):
        # When config={} is passed (and api_key is None), the elif config is not None:
        # branch is taken, calling Memory.from_config(config).
        assert toolkit_config is not None

        # Check the *instance* of mem0client is the mock returned by Memory.from_config
        assert isinstance(toolkit_config.mem0client, MagicMock)
        assert toolkit_config.mem0client == mock_memory_instance  # Check it's the correct mock

        # Check the CLASS method MockMemory.from_config was called once
        MockMemory.from_config.assert_called_once_with({})  # Called with config={}

        # Ensure the MockMemory constructor (else branch) was NOT called
        # We access the underlying mock constructor via MockMemory itself
        # Check call_count on the class mock itself, not the instance mock
        # assert MockMemory.call_count == 0 # Constructor should not have been called (REMOVED - Fixture causes one call)

        # Ensure MemoryClient constructor wasn't called
        MockMemoryClient.assert_not_called()

    def test_init_with_api_key(self, toolkit_api_key, mock_memory_client_instance):
        assert toolkit_api_key is not None
        # Check the *instance* of mem0client is the mock returned by MemoryClient constructor
        assert isinstance(toolkit_api_key.mem0client, MagicMock)
        assert toolkit_api_key.mem0client == mock_memory_client_instance  # Check it's the correct mock
        # Check the class constructor was called
        MockMemoryClient.assert_called_once_with(api_key="fake-api-key")
        MockMemory.from_config.assert_not_called()  # Ensure Memory.from_config wasn't called

    # -- Helper Method Tests (Corrected) --
    def test_get_user_id_from_arg(self, toolkit_config):
        user_id = toolkit_config._get_user_id("test_method", user_id="arg_user")
        assert user_id == "arg_user"

    def test_get_user_id_no_id_provided(self, toolkit_config):
        # Use an existing toolkit instance, doesn't matter which one
        with pytest.raises(ValueError, match="user_id must be provided in the method call"):
            toolkit_config._get_user_id("test_method", user_id=None)

    # -- Add Memory Tests (Corrected) --
    def test_add_memory_success_arg_id(self, toolkit_config, mock_memory_instance):
        # toolkit_config uses Memory.from_config -> mock_memory_instance
        result_str = toolkit_config.add_memory(messages="Test message", user_id="test_user_add")
        # No metadata kwarg passed
        mock_memory_instance.add.assert_called_once_with(
            [{"role": "user", "content": "Test message"}],
            user_id="test_user_add",
        )
        # The return value from the mock is already a dict, toolkit json.dumps it
        expected_result = {"results": [{"id": "mem-add-123", "memory": "added memory", "event": "ADD"}]}
        assert json.loads(result_str) == expected_result

    def test_add_memory_dict_message(self, toolkit_config, mock_memory_instance):
        # toolkit_config uses Memory.from_config -> mock_memory_instance
        toolkit_config.add_memory(messages={"role": "user", "content": "Dict message"}, user_id="user1")
        # No metadata kwarg passed
        mock_memory_instance.add.assert_called_once_with(
            [{"role": "user", "content": "Dict message"}],
            user_id="user1",
        )

    def test_add_memory_invalid_message_type(self, toolkit_config):
        # user_id is mandatory now, so pass it
        result = toolkit_config.add_memory(messages=123, user_id="user1")
        assert "Error: Invalid input type" in result

    def test_add_memory_no_user_id(self, toolkit_config):
        # toolkit_config uses Memory.from_config -> mock_memory_instance
        # Method catches ValueError and returns an error string
        result = toolkit_config.add_memory(messages="No user ID test")  # No user_id provided
        expected_error_msg = "Error in add_memory: A user_id must be provided in the method call."
        assert expected_error_msg in result  # Check if the specific error from _get_user_id is in the returned string

    # -- Search Memory Tests (Corrected) --
    def test_search_memory_success_arg_id(self, toolkit_config, mock_memory_instance):
        # toolkit_config uses Memory.from_config -> mock_memory_instance
        # Pass limit explicitly in the test call
        result_str = toolkit_config.search_memory(query="find stuff", user_id="test_user_search")
        # Expect limit to be passed explicitly
        mock_memory_instance.search.assert_called_once_with(query="find stuff", user_id="test_user_search")
        # Mock returns dict with "results", toolkit extracts list and json.dumps it
        expected_result = [{"id": "mem-search-456", "memory": "found memory", "score": 0.9}]
        assert json.loads(result_str) == expected_result

    def test_search_memory_success_default_limit(self, toolkit_config, mock_memory_instance):
        # toolkit_config uses Memory.from_config -> mock_memory_instance
        # Call without limit to test default
        toolkit_config.search_memory(query="default search", user_id="user_default_limit")
        # Expect toolkit default limit (5) to be passed explicitly
        mock_memory_instance.search.assert_called_once_with(
            query="default search",
            user_id="user_default_limit",
        )

    def test_search_memory_no_user_id(self, toolkit_config):
        # toolkit_config uses Memory.from_config -> mock_memory_instance
        # Method catches ValueError and returns an error string
        result = toolkit_config.search_memory(query="No user ID search")  # No user_id provided
        expected_error_msg = "Error in search_memory: A user_id must be provided in the method call."
        assert result == expected_error_msg  # search_memory returns the exact error string from ValueError

    def test_search_memory_api_key_list_return(self, toolkit_api_key, mock_memory_client_instance):
        # toolkit_api_key uses MemoryClient -> mock_memory_client_instance
        # Mock returns list directly
        result_str = toolkit_api_key.search_memory(query="client search", user_id="default_user_api")
        # Expect specified limit (7) to be passed explicitly
        mock_memory_client_instance.search.assert_called_once_with(
            query="client search",
            user_id="default_user_api",
        )
        # Mock returns list, toolkit json.dumps it
        expected_result = [{"id": "mem-client-search-456", "memory": "found client memory", "score": 0.8}]
        assert json.loads(result_str) == expected_result

    # -- Get Memory Tests --
    def test_get_memory_success(self, toolkit_api_key, mock_memory_client_instance):
        result_str = toolkit_api_key.get_memory(memory_id="mem-client-get-789")
        mock_memory_client_instance.get.assert_called_once_with(memory_id="mem-client-get-789")
        expected = {"id": "mem-client-get-789", "memory": "specific client memory"}
        assert json.loads(result_str) == expected

    def test_get_memory_not_found(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.get.return_value = None  # Simulate not found
        result_str = toolkit_api_key.get_memory(memory_id="not-found-id")
        mock_memory_client_instance.get.assert_called_once_with(memory_id="not-found-id")
        assert "not found" in result_str

    def test_get_memory_error(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.get.side_effect = Exception("Test get error")
        result_str = toolkit_api_key.get_memory(memory_id="error-id")
        assert "Error getting memory error-id: Test get error" in result_str

    # -- Update Memory Tests --
    def test_update_memory_success(self, toolkit_api_key, mock_memory_client_instance):
        result_str = toolkit_api_key.update_memory(memory_id="mem-client-update-1", data="new data")
        mock_memory_client_instance.update.assert_called_once_with(memory_id="mem-client-update-1", data="new data")
        expected = {"message": "Client memory updated successfully!"}
        assert json.loads(result_str) == expected

    def test_update_memory_success_no_response(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.update.return_value = None  # Simulate None response
        result_str = toolkit_api_key.update_memory(memory_id="mem-client-update-none", data="new data none")
        mock_memory_client_instance.update.assert_called_once_with(
            memory_id="mem-client-update-none", data="new data none"
        )
        assert "updated successfully (no detailed response)" in result_str

    def test_update_memory_error(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.update.side_effect = Exception("Test update error")
        result_str = toolkit_api_key.update_memory(memory_id="error-id", data="error data")
        assert "Error updating memory error-id: Test update error" in result_str

    # -- Delete Memory Tests --
    def test_delete_memory_success(self, toolkit_api_key, mock_memory_client_instance):
        result_str = toolkit_api_key.delete_memory(memory_id="mem-client-delete-1")
        mock_memory_client_instance.delete.assert_called_once_with(memory_id="mem-client-delete-1")
        assert "deleted successfully" in result_str

    def test_delete_memory_error(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.delete.side_effect = Exception("Test delete error")
        result_str = toolkit_api_key.delete_memory(memory_id="error-id")
        assert "Error deleting memory error-id: Test delete error" in result_str

    # -- Get Memory History Tests --
    def test_get_memory_history_success(self, toolkit_api_key, mock_memory_client_instance):
        result_str = toolkit_api_key.get_memory_history(memory_id="client-hist-1")
        mock_memory_client_instance.history.assert_called_once_with(memory_id="client-hist-1")
        expected = [{"event": "ADD", "memory_id": "client-hist-1"}]
        assert json.loads(result_str) == expected

    def test_get_memory_history_error(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.history.side_effect = Exception("Test history error")
        result_str = toolkit_api_key.get_memory_history(memory_id="error-id")
        assert "Error getting history for memory error-id: Test history error" in result_str

    # -- Get All Memories Tests --
    def test_get_all_memories_success(self, toolkit_api_key, mock_memory_client_instance):
        # Mock returns list directly for MemoryClient
        result_str = toolkit_api_key.get_all_memories(user_id="user-all-1")
        mock_memory_client_instance.get_all.assert_called_once_with(user_id="user-all-1")
        expected = [{"id": "mem-client-all-1", "memory": "all client mem 1"}]
        assert json.loads(result_str) == expected

    def test_get_all_memories_success_dict_return(self, toolkit_config, mock_memory_instance):
        # Use toolkit_config which uses Memory mock returning dict
        # Ensure the mock returns a dict for this test case
        mock_memory_instance.get_all.return_value = {"results": [{"id": "mem-all-1", "memory": "all mem 1"}]}
        result_str = toolkit_config.get_all_memories(user_id="user-all-dict")
        mock_memory_instance.get_all.assert_called_once_with(user_id="user-all-dict")
        expected = [{"id": "mem-all-1", "memory": "all mem 1"}]
        assert json.loads(result_str) == expected

    def test_get_all_memories_no_user_id(self, toolkit_api_key):
        result_str = toolkit_api_key.get_all_memories(user_id=None)
        expected_error_msg = "Error in get_all_memories: A user_id must be provided in the method call."
        assert result_str == expected_error_msg  # Check for the exact error string

    def test_get_all_memories_error(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.get_all.side_effect = Exception("Test get_all error")
        result_str = toolkit_api_key.get_all_memories(user_id="error-user")
        assert "Error getting all memories: Test get_all error" in result_str

    # -- Delete All Memories Tests --
    def test_delete_all_memories_success(self, toolkit_api_key, mock_memory_client_instance):
        result_str = toolkit_api_key.delete_all_memories(user_id="user-delete-all-1")
        mock_memory_client_instance.delete_all.assert_called_once_with(user_id="user-delete-all-1")
        expected_str = "Successfully deleted all memories associated with user_id: user-delete-all-1."
        assert result_str == expected_str  # Check for exact string match

    def test_delete_all_memories_no_user_id(self, toolkit_api_key):
        result_str = toolkit_api_key.delete_all_memories(user_id=None)
        expected_error_msg = "Error in delete_all_memories: A user_id must be provided in the method call."
        # The method currently catches the ValueError and returns a generic error string
        assert "Error deleting all memories:" in result_str
        assert expected_error_msg in result_str  # Check the original ValueError message is included

    def test_delete_all_memories_error(self, toolkit_api_key, mock_memory_client_instance):
        mock_memory_client_instance.delete_all.side_effect = Exception("Test delete_all error")
        result_str = toolkit_api_key.delete_all_memories(user_id="error-user")
        assert "Error deleting all memories: Test delete_all error" in result_str
