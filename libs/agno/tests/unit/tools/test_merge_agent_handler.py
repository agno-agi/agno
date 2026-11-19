"""Unit tests for MergeAgentHandlerTools."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.merge_agent_handler import MergeAgentHandlerTools


@pytest.fixture
def merge_tools():
    """Create MergeAgentHandlerTools with defaults for tests."""
    tools = MergeAgentHandlerTools(
        api_key="test_api_key",
        tool_pack_id="tp_default",
        registered_user_id="ru_default",
    )
    yield tools
    tools.close()


def _response(payload):
    """Create a mocked HTTP response with JSON payload."""
    mocked_response = Mock()
    mocked_response.raise_for_status = Mock()
    mocked_response.json.return_value = payload
    return mocked_response


def test_initialization_defaults():
    """Test default initialization registers all tools."""
    tools = MergeAgentHandlerTools(api_key="test_api_key")
    function_names = [func.name for func in tools.functions.values()]

    assert "list_tool_packs" in function_names
    assert "list_registered_users" in function_names
    assert "list_tools" in function_names
    assert "call_tool" in function_names
    assert tools.name == "merge_agent_handler_tools"
    tools.close()


def test_initialization_with_all_flag():
    """Test that all=True enables all tools regardless of individual flags."""
    tools = MergeAgentHandlerTools(
        api_key="test_api_key",
        enable_list_tool_packs=False,
        enable_list_registered_users=False,
        enable_list_tools=False,
        enable_call_tool=False,
        all=True,
    )
    function_names = [func.name for func in tools.functions.values()]
    assert set(function_names) == {"list_tool_packs", "list_registered_users", "list_tools", "call_tool"}
    tools.close()


def test_initialization_without_api_key():
    """Test initialization without API key fails."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="Merge API key is required"):
            MergeAgentHandlerTools()


def test_env_var_fallback_for_api_key():
    """Test MERGE_API_KEY fallback when api_key is not provided."""
    with patch.dict("os.environ", {"MERGE_API_KEY": "env_key"}):
        tools = MergeAgentHandlerTools(
            enable_list_tool_packs=False,
            enable_list_registered_users=False,
            enable_list_tools=False,
            enable_call_tool=False,
        )
        assert tools.api_key == "env_key"
        tools.close()


def test_enable_flags_control_tool_registration():
    """Test enable flags control which tools are registered."""
    tools = MergeAgentHandlerTools(
        api_key="test_api_key",
        enable_list_tool_packs=False,
        enable_list_registered_users=False,
        enable_list_tools=False,
        enable_call_tool=True,
    )
    function_names = [func.name for func in tools.functions.values()]
    assert function_names == ["call_tool"]
    tools.close()


def test_list_tool_packs_with_pagination(merge_tools):
    """Test list_tool_packs fetches paginated responses."""
    first_page = {
        "results": [{"id": "tp_1", "name": "Pack One", "connectors": [{"name": "Gong", "slug": "gong"}]}],
        "next": "https://ah-api.merge.dev/api/v1/tool-packs/?page=2",
    }
    second_page = {"results": [{"id": "tp_2", "name": "Pack Two", "connectors": []}], "next": None}

    with patch.object(merge_tools._client, "get", side_effect=[_response(first_page), _response(second_page)]) as get:
        result = json.loads(merge_tools.list_tool_packs())

    assert [pack["id"] for pack in result] == ["tp_1", "tp_2"]
    assert result[0]["connectors"][0]["slug"] == "gong"
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["params"]["page"] == "1"
    assert get.call_args_list[1].kwargs["params"]["page"] == "2"


def test_list_registered_users_with_test_environment(merge_tools):
    """Test list_registered_users passes is_test filter."""
    payload = {
        "results": [{"id": "ru_1", "origin_user_name": "Alex", "is_test": True}],
        "next": None,
    }
    with patch.object(merge_tools._client, "get", return_value=_response(payload)) as get:
        result = json.loads(merge_tools.list_registered_users(environment="test"))

    assert result[0]["id"] == "ru_1"
    assert result[0]["is_test"] is True
    assert get.call_args.kwargs["params"]["is_test"] == "true"


def test_list_registered_users_invalid_environment(merge_tools):
    """Test list_registered_users handles invalid environment input."""
    result = json.loads(merge_tools.list_registered_users(environment="staging"))
    assert "error" in result
    assert "environment must be either 'production' or 'test'" in result["error"]


def test_list_tools_sends_tools_list_rpc(merge_tools):
    """Test list_tools sends tools/list MCP request and parses tools."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "gong__get_user", "description": "Get user", "inputSchema": {"type": "object"}}]},
    }
    with patch.object(merge_tools._client, "post", return_value=_response(payload)) as post:
        result = json.loads(merge_tools.list_tools())

    assert result[0]["name"] == "gong__get_user"
    request_payload = post.call_args.kwargs["json"]
    assert request_payload["method"] == "tools/list"
    assert request_payload["params"] == {}


def test_call_tool_wraps_input_arguments(merge_tools):
    """Test call_tool wraps arguments under input."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
    }
    with patch.object(merge_tools._client, "post", return_value=_response(payload)) as post:
        result = json.loads(merge_tools.call_tool("gong__get_user", arguments='{"id": "usr_123"}'))

    assert result["isError"] is False
    request_payload = post.call_args.kwargs["json"]
    assert request_payload["method"] == "tools/call"
    assert request_payload["params"]["name"] == "gong__get_user"
    assert request_payload["params"]["arguments"] == {"input": {"id": "usr_123"}}


def test_call_tool_returns_error_for_mcp_error(merge_tools):
    """Test call_tool handles MCP error payload."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": 500, "message": "boom"},
    }
    with patch.object(merge_tools._client, "post", return_value=_response(payload)):
        result = json.loads(merge_tools.call_tool("gong__get_user", arguments="{}"))

    assert result["code"] == 500
    assert 'Tool "gong__get_user" returned error: boom' in result["error"]


def test_call_tool_handles_is_error_content(merge_tools):
    """Test call_tool handles MCP isError responses."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"isError": True, "content": [{"type": "text", "text": "permission denied"}]},
    }
    with patch.object(merge_tools._client, "post", return_value=_response(payload)):
        result = json.loads(merge_tools.call_tool("gong__get_user", arguments='{"id": "usr_123"}'))

    assert 'Tool "gong__get_user" failed: permission denied' in result["error"]


def test_call_tool_invalid_arguments_json(merge_tools):
    """Test call_tool rejects invalid JSON string for arguments."""
    result = json.loads(merge_tools.call_tool("gong__get_user", arguments="{invalid"))
    assert "arguments must be a valid JSON string representing an object." in result["error"]


def test_call_tool_missing_identifiers_without_defaults():
    """Test call_tool returns error when required IDs are missing."""
    tools = MergeAgentHandlerTools(api_key="test_api_key", tool_pack_id=None, registered_user_id=None)
    result = json.loads(tools.call_tool("gong__get_user", arguments='{"id": "usr_123"}'))
    assert "tool_pack_id is required" in result["error"]
    tools.close()
