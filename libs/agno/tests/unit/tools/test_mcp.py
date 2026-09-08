import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import StdioServerParameters
from mcp.types import CallToolResult, TextContent

from agno.tools.function import Function, FunctionCall, ToolResult
from agno.tools.mcp import MCPTools
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from agno.utils.mcp import get_entrypoint_for_tool


class _AsyncContextManager:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_sse_transport_without_url_nor_sse_client_params():
    """Test that ValueError is raised when transport is SSE but URL is not provided."""
    with pytest.raises(ValueError, match="One of 'url' or 'server_params' parameters must be provided"):
        async with MCPTools(transport="sse"):
            pass


@pytest.mark.asyncio
async def test_stdio_transport_without_command_nor_server_params():
    """Test that ValueError is raised when transport is stdio but server_params is None."""
    with pytest.raises(ValueError, match="One of 'command' or 'server_params' parameters must be provided"):
        async with MCPTools(transport="stdio"):
            pass


@pytest.mark.asyncio
async def test_streamable_http_transport_without_url_nor_server_params():
    """Test that ValueError is raised when transport is streamable_http but URL is not provided."""
    with pytest.raises(ValueError, match="One of 'url' or 'server_params' parameters must be provided"):
        async with MCPTools(transport="streamable-http"):
            pass


def test_empty_command_string():
    """Test that ValueError is raised when command string is empty."""
    with pytest.raises(ValueError, match="MCP command can't be empty"):
        # Mock shlex.split to return an empty list
        with patch("shlex.split", return_value=[]):
            MCPTools(command="")


def test_url_defaults_to_streamable_http_transport():
    """Test that transport defaults to streamable-http when url is provided."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    assert tools.transport == "streamable-http"


def test_stdio_transport_with_url_overrides_to_streamable_http():
    """Test that stdio transport gets overridden to streamable-http when url is present."""
    tools = MCPTools(url="http://localhost:8080/mcp", transport="stdio")
    assert tools.transport == "streamable-http"


def test_default_name_derived_from_url_is_distinct_and_stable():
    """Two servers get distinct default names; the same server always gets the same name."""
    docs = MCPTools(url="https://docs.example.com/mcp")
    search = MCPTools(url="https://search.example.com/mcp")
    assert docs.name != search.name
    assert docs.name != "MCPTools"
    assert docs.name == MCPTools(url="https://docs.example.com/mcp").name


def test_default_name_drops_url_query_and_fragment():
    """Credentials passed as query params must never leak into the toolkit name."""
    tools = MCPTools(url="https://server.example.com/mcp?api_key=supersecret123#fragment")
    assert "supersecret123" not in tools.name
    assert "fragment" not in tools.name
    assert tools.name == MCPTools(url="https://server.example.com/mcp").name


def test_default_name_drops_url_userinfo():
    """Credentials passed as URL userinfo must never leak into the toolkit name."""
    tools = MCPTools(url="https://alice:hunter2pass@server.example.com/mcp")
    assert "hunter2pass" not in tools.name
    assert "alice" not in tools.name
    assert tools.name == MCPTools(url="https://server.example.com/mcp").name


def test_default_name_derived_from_command():
    server_a = MCPTools(command="npx -y @acme/server-a")
    server_b = MCPTools(command="npx -y @acme/server-b")
    assert server_a.name != server_b.name
    assert server_a.name != "MCPTools"


def test_default_name_derived_from_server_params():
    http_tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="https://a.example.com/mcp"), transport="streamable-http"
    )
    stdio_tools = MCPTools(
        server_params=StdioServerParameters(command="npx", args=["-y", "@acme/server-b"]), transport="stdio"
    )
    assert http_tools.name != "MCPTools"
    assert stdio_tools.name != "MCPTools"
    assert http_tools.name != stdio_tools.name


def test_session_only_init_falls_back_to_default_name():
    tools = MCPTools(session=AsyncMock())
    assert tools.name == "MCPTools"


def test_explicit_name_overrides_derived_default():
    tools = MCPTools(url="https://docs.example.com/mcp", name="agno_docs")
    assert tools.name == "agno_docs"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    (
        {"command": "npx foo", "include_tools": ["foo"]},
        {"command": "npx foo", "exclude_tools": ["foo"]},
    ),
)
async def test_mcp_include_exclude_tools_bad_values(kwargs):
    """Test that _check_tools_filters raises ValueError during initialize"""
    session_mock = AsyncMock()
    tool_mock = AsyncMock()
    tool_mock.__name__ = "baz"
    tools = AsyncMock()
    tools.tools = [tool_mock]
    session_mock.list_tools.return_value = tools

    # _check_tools_filters should be bypassed during __init__
    tools = MCPTools(**kwargs)
    with pytest.raises(ValueError, match="not present in the toolkit"):
        tools.session = session_mock
        await tools.build_tools()


# =============================================================================
# header_provider tests
# =============================================================================


def test_is_valid_header_provider_with_http_transport():
    """Test that header_provider is valid for HTTP transports."""
    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {})
    assert tools.header_provider is not None


def test_header_provider_with_stdio_transport_raises_error():
    """Test that ValueError is raised when header_provider is used with stdio transport."""
    with pytest.raises(ValueError, match="header_provider is not supported with 'stdio' transport"):
        MCPTools(command="npx foo", transport="stdio", header_provider=lambda: {})


def test_call_header_provider_no_params():
    """Test header_provider with no parameters."""
    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {"X-Static": "value"})
    result = tools._call_header_provider()
    assert result == {"X-Static": "value"}


def test_call_header_provider_with_run_context():
    """Test header_provider with run_context parameter."""
    run_context = MagicMock()
    run_context.user_id = "test-user"

    def provider(run_context):
        return {"X-User-ID": run_context.user_id}

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)
    result = tools._call_header_provider(run_context=run_context)
    assert result == {"X-User-ID": "test-user"}


def test_call_header_provider_with_agent():
    """Test header_provider with agent parameter."""
    run_context = MagicMock()
    agent = MagicMock()
    agent.name = "test-agent"

    def provider(run_context, agent):
        return {"X-Agent": agent.name}

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)
    result = tools._call_header_provider(run_context=run_context, agent=agent)
    assert result == {"X-Agent": "test-agent"}


def test_call_header_provider_with_kwargs():
    """Test header_provider with **kwargs."""

    def provider(**kwargs):
        return {
            "X-Has-Agent": str(kwargs.get("agent") is not None),
            "X-Has-Team": str(kwargs.get("team") is not None),
        }

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)
    result = tools._call_header_provider(run_context=MagicMock(), agent=MagicMock(), team=None)
    assert result == {"X-Has-Agent": "True", "X-Has-Team": "False"}


def test_call_header_provider_with_team():
    """Test header_provider receives team when provided."""
    run_context = MagicMock()
    agent = MagicMock()
    agent.name = "member-agent"
    team = MagicMock()
    team.name = "test-team"

    def provider(run_context, agent, team):
        return {
            "X-Agent": agent.name if agent else "none",
            "X-Team": team.name if team else "none",
        }

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)
    result = tools._call_header_provider(run_context=run_context, agent=agent, team=team)
    assert result == {"X-Agent": "member-agent", "X-Team": "test-team"}


@pytest.mark.asyncio
async def test_connect_merges_init_headers_when_streamable_http_headers_default_to_none():
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
        header_provider=lambda: {"Authorization": "Bearer token"},
    )

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as streamable_http_mock,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert streamable_http_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_connect_merges_init_headers_when_sse_headers_default_to_none():
    tools = MCPTools(
        server_params=SSEClientParams(url="http://localhost:8080/sse"),
        transport="sse",
        header_provider=lambda: {"Authorization": "Bearer token"},
    )

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as sse_client_mock,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert sse_client_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_connect_applies_header_provider_when_using_url_only_streamable_http():
    """Regression for #9442: header_provider must authenticate the connect handshake.

    Reproduces the common url= + header_provider(run_context) pattern without
    StreamableHTTPClientParams.
    """

    def header_provider(run_context):
        return {"Authorization": "Bearer connect-token"}

    tools = MCPTools(
        url="http://localhost:8000/mcp",
        transport="streamable-http",
        header_provider=header_provider,
    )

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as streamable_http_mock,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    # The builder takes (transport, params, ...); url and headers both live in params.
    assert streamable_http_mock.call_args.args[1]["url"] == "http://localhost:8000/mcp"
    assert streamable_http_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer connect-token"}


@pytest.mark.asyncio
async def test_connect_applies_static_headers_when_using_url_only_streamable_http():
    tools = MCPTools(
        url="http://localhost:8000/mcp",
        transport="streamable-http",
        headers={"Authorization": "Bearer static-token"},
    )

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as http_client_factory,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert http_client_factory.call_args.args[1]["headers"] == {"Authorization": "Bearer static-token"}


@pytest.mark.asyncio
async def test_connect_merges_static_headers_and_header_provider_on_streamable_http():
    tools = MCPTools(
        url="http://localhost:8000/mcp",
        transport="streamable-http",
        headers={"X-Static": "a", "Authorization": "Bearer static"},
        header_provider=lambda: {"Authorization": "Bearer dynamic", "X-Dynamic": "b"},
    )

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as http_client_factory,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert http_client_factory.call_args.args[1]["headers"] == {
        "X-Static": "a",
        "Authorization": "Bearer dynamic",
        "X-Dynamic": "b",
    }


@pytest.mark.asyncio
async def test_connect_applies_header_provider_when_using_url_only_sse():
    def header_provider(run_context):
        return {"Authorization": "Bearer connect-token"}

    tools = MCPTools(
        url="http://localhost:8000/sse",
        transport="sse",
        header_provider=header_provider,
    )

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as sse_client_mock,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert sse_client_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer connect-token"}


def test_headers_with_stdio_transport_raises_error():
    with pytest.raises(ValueError, match="headers is not supported with 'stdio' transport"):
        MCPTools(command="npx foo", transport="stdio", headers={"Authorization": "Bearer token"})


@pytest.mark.asyncio
async def test_mcp_toolbox_headers_not_sent_to_mcp_connect():
    """MCPToolbox toolbox-core credentials in self.headers must not reach the MCP handshake.

    Regression for the Greptile P1 on #9444: MCPTools merges MCP-intended headers for
    connect/session, but MCPToolbox historically stores toolbox-core client_headers in
    self.headers. Those must stay isolated from the MCP transport.
    """
    import sys
    from types import ModuleType

    toolbox_core = ModuleType("toolbox_core")
    toolbox_core.ToolboxClient = MagicMock()
    sys.modules["toolbox_core"] = toolbox_core
    sys.modules.pop("agno.tools.mcp_toolbox", None)

    from agno.tools.mcp_toolbox import MCPToolbox

    toolbox_headers = {"Authorization": "Bearer toolbox-secret"}
    tools = MCPToolbox(
        url="http://localhost:8000",
        headers=toolbox_headers,
        append_mcp_to_url=True,
    )
    assert tools.headers == toolbox_headers
    assert tools._merge_http_headers() == {}

    with (
        patch(
            "agno.tools.mcp.mcp._build_fastmcp_client",
            return_value=_AsyncContextManager(MagicMock()),
        ) as streamable_http_mock,
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    # Headers ride on the fastmcp transport built here, so the params dict is where a
    # leaked toolbox credential would show up.
    sent_headers = (
        streamable_http_mock.call_args.args[1].get("headers") if streamable_http_mock.call_args else None
    ) or {}
    assert "Authorization" not in sent_headers
    assert "toolbox-secret" not in str(streamable_http_mock.call_args)


@pytest.mark.asyncio
async def test_get_session_for_run_merges_headers_when_sse_headers_default_to_none():
    tools = MCPTools(
        server_params=SSEClientParams(url="http://localhost:8080/sse"),
        transport="sse",
        header_provider=lambda run_context: {"Authorization": "Bearer token"},
    )
    # Provide a default session so the fast-path check passes
    tools.session = MagicMock()

    run_context = MagicMock()
    run_context.run_id = "run-sse-none-headers"

    with (
        patch("agno.tools.mcp.mcp._build_fastmcp_client") as sse_mock,
    ):
        mock_session = AsyncMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        sse_mock.return_value = mock_session_context

        session = await tools.get_session_for_run(run_context=run_context)

    assert sse_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer token"}
    assert session is mock_session


@pytest.mark.asyncio
async def test_get_session_for_run_merges_headers_when_streamable_http_headers_default_to_none():
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
        header_provider=lambda run_context: {"Authorization": "Bearer token"},
    )
    tools.session = MagicMock()

    run_context = MagicMock()
    run_context.run_id = "run-http-none-headers"

    with (
        patch("agno.tools.mcp.mcp._build_fastmcp_client") as streamable_mock,
    ):
        mock_session = AsyncMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        streamable_mock.return_value = mock_session_context

        session = await tools.get_session_for_run(run_context=run_context)

    assert streamable_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer token"}
    assert session is mock_session


# =============================================================================
# Session caching tests - verify no collisions between runs
# =============================================================================


def test_different_run_ids_get_different_cache_entries():
    """Test that different run_ids result in separate session cache entries."""
    headers_called_with = []

    def provider(run_context, agent=None, team=None):
        headers_called_with.append(run_context.run_id)
        return {"X-Run-ID": run_context.run_id}

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)

    # Simulate two different runs
    run1 = MagicMock()
    run1.run_id = "run-1"
    run2 = MagicMock()
    run2.run_id = "run-2"

    # Call header provider for both runs
    result1 = tools._call_header_provider(run_context=run1)
    result2 = tools._call_header_provider(run_context=run2)

    # Each run should get its own headers
    assert result1 == {"X-Run-ID": "run-1"}
    assert result2 == {"X-Run-ID": "run-2"}
    assert headers_called_with == ["run-1", "run-2"]


def test_same_session_different_runs_no_collision():
    """Test that multiple runs in same session get unique headers based on run_id."""
    call_count = {"count": 0}

    def provider(run_context, agent=None, team=None):
        call_count["count"] += 1
        return {
            "X-User-ID": run_context.user_id,
            "X-Session-ID": run_context.session_id,
            "X-Run-ID": run_context.run_id,
            "X-Call-Count": str(call_count["count"]),
        }

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)

    # Same session, same user, but different runs
    run1 = MagicMock()
    run1.user_id = "user-1"
    run1.session_id = "session-1"
    run1.run_id = "run-1"

    run2 = MagicMock()
    run2.user_id = "user-1"
    run2.session_id = "session-1"
    run2.run_id = "run-2"

    result1 = tools._call_header_provider(run_context=run1)
    result2 = tools._call_header_provider(run_context=run2)

    # Headers should be unique per run
    assert result1["X-Run-ID"] == "run-1"
    assert result2["X-Run-ID"] == "run-2"
    assert result1["X-Call-Count"] == "1"
    assert result2["X-Call-Count"] == "2"
    # But share same user/session
    assert result1["X-User-ID"] == result2["X-User-ID"] == "user-1"
    assert result1["X-Session-ID"] == result2["X-Session-ID"] == "session-1"


def test_header_provider_called_with_correct_context_for_agent_vs_team():
    """Test header_provider receives correct agent/team context."""
    calls = []

    def provider(run_context, agent=None, team=None):
        calls.append(
            {
                "agent_name": agent.name if agent else None,
                "team_name": team.name if team else None,
            }
        )
        return {}

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=provider)
    run_context = MagicMock()
    run_context.run_id = "test-run"

    # Simulate standalone agent call
    standalone_agent = MagicMock()
    standalone_agent.name = "standalone-agent"
    tools._call_header_provider(run_context=run_context, agent=standalone_agent, team=None)

    # Simulate team member call
    member_agent = MagicMock()
    member_agent.name = "member-agent"
    team = MagicMock()
    team.name = "my-team"
    tools._call_header_provider(run_context=run_context, agent=member_agent, team=team)

    assert len(calls) == 2
    # First call: standalone agent, no team
    assert calls[0]["agent_name"] == "standalone-agent"
    assert calls[0]["team_name"] is None
    # Second call: member agent with team
    assert calls[1]["agent_name"] == "member-agent"
    assert calls[1]["team_name"] == "my-team"


# =============================================================================
# TTL cleanup tests
# =============================================================================


@pytest.mark.asyncio
async def test_stale_sessions_cleaned_up_on_new_run():
    """Test that stale sessions are cleaned up when a new run requests a session."""
    import time

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {})
    tools._session_ttl_seconds = 0.1  # 100ms TTL for testing

    # Simulate an old session from a previous run (use AsyncMock for async __aexit__)
    old_session = MagicMock()
    old_context = AsyncMock()
    old_session_context = AsyncMock()
    tools._run_sessions["old-run-id"] = (old_session, time.time() - 1.0)  # 1 second ago
    tools._run_session_contexts["old-run-id"] = (old_context, old_session_context)

    # Wait for TTL to expire
    time.sleep(0.15)

    # Now simulate a new run requesting a session - this should trigger cleanup
    # We need to mock the session creation since we don't have a real MCP server
    with patch("agno.tools.mcp.mcp._build_fastmcp_client") as mock_client:
        mock_new_session = AsyncMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_new_session
        mock_client.return_value = mock_session_context

        new_run_context = MagicMock()
        new_run_context.run_id = "new-run-id"

        # This should clean up old session and create new one
        session = await tools.get_session_for_run(run_context=new_run_context)

        # Old session should be cleaned up
        assert "old-run-id" not in tools._run_sessions
        # New session should exist
        assert "new-run-id" in tools._run_sessions
        assert session == mock_new_session


# =============================================================================
# HITL (Human-in-the-Loop) and control flow tests
# =============================================================================


def test_hitl_params_accepted_in_constructor():
    """Test that HITL parameters can be passed to MCPTools constructor."""
    tools = MCPTools(
        url="https://example.com/mcp",
        requires_confirmation_tools=["tool1", "tool2"],
        external_execution_required_tools=["tool3"],
        stop_after_tool_call_tools=["tool4"],
        show_result_tools=["tool5"],
    )

    assert tools.requires_confirmation_tools == ["tool1", "tool2"]
    assert tools.external_execution_required_tools == ["tool3"]
    assert tools.stop_after_tool_call_tools == ["tool4"]
    assert tools.show_result_tools == ["tool5"]


def test_hitl_params_default_to_empty_lists():
    """Test that HITL parameters default to empty lists when not provided."""
    tools = MCPTools(url="https://example.com/mcp")

    assert tools.requires_confirmation_tools == []
    assert tools.external_execution_required_tools == []
    assert tools.stop_after_tool_call_tools == []
    assert tools.show_result_tools == []


@pytest.mark.asyncio
async def test_hitl_params_applied_to_functions():
    """Test that HITL parameters are applied to Function objects during build_tools."""
    tools = MCPTools(
        url="https://example.com/mcp",
        requires_confirmation_tools=["SearchTool"],
        external_execution_required_tools=["ExternalTool"],
        stop_after_tool_call_tools=["StopTool"],
        show_result_tools=["ShowTool"],
    )

    # Create mock tools from MCP server
    def create_mock_tool(name, description):
        mock_tool = MagicMock()
        mock_tool.name = name
        mock_tool.description = description
        mock_tool.input_schema = {"type": "object", "properties": {}}
        return mock_tool

    mock_tools_result = MagicMock()
    mock_tools_result.tools = [
        create_mock_tool("SearchTool", "Search for things"),
        create_mock_tool("ExternalTool", "External execution"),
        create_mock_tool("StopTool", "Stop after call"),
        create_mock_tool("ShowTool", "Show result"),
        create_mock_tool("NormalTool", "Normal tool without HITL"),
    ]

    mock_session = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=mock_tools_result)

    tools.session = mock_session
    tools._initialized = False

    with patch("agno.tools.mcp.mcp.get_entrypoint_for_tool", return_value=lambda: "result"):
        await tools.build_tools()

    # Verify requires_confirmation is applied
    assert tools.functions["SearchTool"].requires_confirmation is True
    assert tools.functions["SearchTool"].external_execution is False

    # Verify external_execution is applied
    assert tools.functions["ExternalTool"].external_execution is True
    assert tools.functions["ExternalTool"].requires_confirmation is False

    # Verify stop_after_tool_call is applied (and show_result auto-set)
    assert tools.functions["StopTool"].stop_after_tool_call is True
    assert tools.functions["StopTool"].show_result is True

    # Verify show_result is applied independently
    assert tools.functions["ShowTool"].show_result is True
    assert tools.functions["ShowTool"].stop_after_tool_call is False

    # Verify normal tool has no HITL settings
    assert tools.functions["NormalTool"].requires_confirmation is False
    assert tools.functions["NormalTool"].external_execution is False
    assert tools.functions["NormalTool"].stop_after_tool_call is False
    assert tools.functions["NormalTool"].show_result is False


@pytest.mark.asyncio
async def test_hitl_params_with_tool_name_prefix():
    """Test that HITL params work correctly with tool_name_prefix."""
    tools = MCPTools(
        url="https://example.com/mcp",
        tool_name_prefix="myprefix",
        requires_confirmation_tools=["SearchTool"],
    )

    mock_tool = MagicMock()
    mock_tool.name = "SearchTool"
    mock_tool.description = "Search"
    mock_tool.input_schema = {"type": "object", "properties": {}}

    mock_tools_result = MagicMock()
    mock_tools_result.tools = [mock_tool]

    mock_session = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=mock_tools_result)

    tools.session = mock_session
    tools._initialized = False

    with patch("agno.tools.mcp.mcp.get_entrypoint_for_tool", return_value=lambda: "result"):
        await tools.build_tools()

    # Function should be registered with prefix
    assert "myprefix_SearchTool" in tools.functions
    # HITL setting should still be applied (matched by original name)
    assert tools.functions["myprefix_SearchTool"].requires_confirmation is True


# =============================================================================
# Parallel tool call session tests (issue #6094)
# =============================================================================


@pytest.mark.asyncio
async def test_parallel_get_session_for_run_creates_single_session():
    """Parallel calls to get_session_for_run with the same run_id must
    create exactly one session (not one per concurrent coroutine)."""
    import asyncio

    creation_count = {"count": 0}

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {"X-Token": "t"})

    with patch("agno.tools.mcp.mcp._build_fastmcp_client") as mock_client:
        mock_session = AsyncMock()
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_client.return_value = mock_context

        original_aenter = mock_context.__aenter__

        async def slow_aenter(*args, **kwargs):
            creation_count["count"] += 1
            await asyncio.sleep(0.05)
            return await original_aenter(*args, **kwargs)

        mock_context.__aenter__ = slow_aenter

        run_context = MagicMock()
        run_context.run_id = "parallel-run"

        # Fire 5 parallel requests for the same run_id
        sessions = await asyncio.gather(
            tools.get_session_for_run(run_context=run_context),
            tools.get_session_for_run(run_context=run_context),
            tools.get_session_for_run(run_context=run_context),
            tools.get_session_for_run(run_context=run_context),
            tools.get_session_for_run(run_context=run_context),
        )

        # All 5 must receive the same session object
        assert all(s is sessions[0] for s in sessions)
        # The transport context should only have been entered once
        assert creation_count["count"] == 1


@pytest.mark.asyncio
async def test_parallel_get_session_different_run_ids():
    """Parallel calls with different run_ids should create separate sessions."""
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {"X-Token": "t"})

    with patch("agno.tools.mcp.mcp._build_fastmcp_client") as mock_client:
        call_count = {"n": 0}

        def make_mock_session_ctx(*args, **kwargs):
            call_count["n"] += 1
            sess = AsyncMock()
            sess._id = call_count["n"]
            ctx = AsyncMock()
            ctx.__aenter__.return_value = sess
            return ctx

        mock_client.side_effect = make_mock_session_ctx

        rc1 = MagicMock()
        rc1.run_id = "run-a"
        rc2 = MagicMock()
        rc2.run_id = "run-b"

        s1, s2 = await asyncio.gather(
            tools.get_session_for_run(run_context=rc1),
            tools.get_session_for_run(run_context=rc2),
        )

        # Different run_ids get different sessions
        assert s1 is not s2
        assert "run-a" in tools._run_sessions
        assert "run-b" in tools._run_sessions


@pytest.mark.asyncio
async def test_session_creation_lock_exists_after_first_call():
    """Verify the lock is lazily created on first access."""
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {})
    assert tools._session_lock is None

    lock = tools._session_creation_lock
    assert isinstance(lock, asyncio.Lock)
    # Same instance on second access
    assert tools._session_creation_lock is lock


# =============================================================================
# Connect-failure cleanup tests
# =============================================================================


class _FailingAenterContext:
    """Async context manager whose __aenter__ raises.
    Tracks whether cleanup was attempted."""

    def __init__(self, error: Exception):
        self.error = error
        self.aexit_called = False
        self.aclose_called = False

    async def __aenter__(self):
        raise self.error

    async def __aexit__(self, exc_type, exc, tb):
        self.aexit_called = True
        return False

    async def aclose(self):
        self.aclose_called = True


class _SucceedingAenterContext:
    """Async CM whose __aenter__ succeeds with a sentinel value."""

    def __init__(self, value):
        self.value = value
        self.aexit_called = False

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.aexit_called = True
        return False


@pytest.mark.asyncio
async def test_connect_failure_leaves_no_session_behind_streamable_http():
    """A failed connect must leave the toolkit unconnected rather than half-open.

    The fastmcp Client owns transport and session together and unwinds itself when the
    handshake fails, so what matters is the state the toolkit is left in.
    """
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )

    failing_client = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    with patch("agno.tools.mcp.mcp._build_fastmcp_client", return_value=failing_client):
        with pytest.raises(ConnectionRefusedError):
            await tools._connect()

    assert tools.session is None
    assert tools._initialized is False
    assert tools._active_contexts == []


@pytest.mark.asyncio
async def test_connect_failure_leaves_no_session_behind_sse():
    """SSE variant of the connect-failure state check."""
    tools = MCPTools(
        server_params=SSEClientParams(url="http://localhost:8080/sse"),
        transport="sse",
    )

    failing_client = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    with patch("agno.tools.mcp.mcp._build_fastmcp_client", return_value=failing_client):
        with pytest.raises(ConnectionRefusedError):
            await tools._connect()

    assert tools.session is None
    assert tools._initialized is False
    assert tools._active_contexts == []


@pytest.mark.asyncio
async def test_connect_failure_against_a_dead_server_releases_the_http_connection():
    """End-to-end leak check: a real failed handshake must not strand an HTTP client.

    Nothing is mocked here -- the connection to an unused port genuinely fails, which is
    the case the hand-rolled two-stage teardown used to cover.
    """
    import gc

    import httpx2

    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://127.0.0.1:7999/mcp", timeout=3),
        transport="streamable-http",
    )

    with pytest.raises(Exception):
        await tools._connect()

    assert tools.session is None
    assert tools._initialized is False
    assert tools._active_contexts == []

    # close() must stay safe after a failed connect.
    await tools.close()

    gc.collect()
    leaked = [o for o in gc.get_objects() if isinstance(o, httpx2.AsyncClient) and not o.is_closed]
    assert leaked == [], f"failed connect left {len(leaked)} open httpx client(s)"


@pytest.mark.asyncio
async def test_refresh_connection_tool_call_closes_dynamic_session_without_caching():
    """A refresh_connection call should open and close its HTTP session inside
    the same tool-call task instead of leaving it for later cleanup."""
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
        header_provider=lambda run_context: {"Authorization": f"Bearer {run_context.token}"},
        refresh_connection=True,
    )
    fallback_session = _make_session_returning("fallback")
    dynamic_session = _make_session_returning("fresh")
    # One fastmcp Client is transport and session both, so a single context is exited.
    client_context = _SucceedingAenterContext(dynamic_session)

    tool = _make_mcp_tool_mock("search_docs")
    run_context = MagicMock()
    run_context.run_id = "refresh-run"
    run_context.token = "run-token"

    with patch("agno.tools.mcp.mcp._build_fastmcp_client", return_value=client_context) as streamable_mock:
        entrypoint = get_entrypoint_for_tool(tool, fallback_session, mcp_tools_instance=tools)
        result = await entrypoint(_agno_run_context=run_context, query="anyio")

    assert result.content == "fresh"
    dynamic_session.call_tool.assert_awaited_once_with("search_docs", {"query": "anyio"})
    fallback_session.call_tool.assert_not_awaited()
    assert streamable_mock.call_args.args[1]["headers"] == {"Authorization": "Bearer run-token"}
    # The per-run connection is closed inside the tool call, not left for later cleanup.
    assert client_context.aexit_called
    assert tools._run_sessions == {}
    assert tools._run_session_contexts == {}


@pytest.mark.asyncio
async def test_connect_public_does_not_raise_when_mcp_server_unreachable():
    """connect() entrypoint used by the agent run loop and AgentOS /agents endpoint.
    If the MCP server is down it must NOT raise"""
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )

    failing_context = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    with patch("agno.tools.mcp.mcp._build_fastmcp_client", return_value=failing_context):
        # Must not raise — connect() catches and logs.
        await tools.connect()

    assert tools._initialized is False
    assert tools.session is None


@pytest.mark.asyncio
async def test_agent_aget_tools_path_survives_dead_mcp_server():
    """Simulate what GET /agents does, build Agent with an
    MCPTools pointing at a dead server."""
    from uuid import uuid4

    from agno.agent.agent import Agent
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )
    failing_context = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    agent = Agent(tools=[tools], telemetry=False)

    session_id = str(uuid4())
    run_id = str(uuid4())

    with patch("agno.tools.mcp.mcp._build_fastmcp_client", return_value=failing_context):
        agent_tools = await agent.aget_tools(
            session=AgentSession(session_id=session_id, session_data={}),
            run_response=RunOutput(run_id=run_id, session_id=session_id),
            run_context=RunContext(run_id=run_id, session_id=session_id),
            check_mcp_tools=False,
        )

    # /agents must complete
    assert isinstance(agent_tools, list)

    # MCP left in clean state
    assert tools._initialized is False
    assert tools._context is None
    assert tools._session_context is None


@pytest.mark.asyncio
async def test_parallel_calls_no_deadlock_with_timeout():
    """Ensure parallel get_session_for_run completes within a reasonable time
    (regression test for the hang described in issue #6094)."""
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {"X-Token": "t"})

    with patch("agno.tools.mcp.mcp._build_fastmcp_client") as mock_client:
        mock_session = AsyncMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_client.return_value = mock_session_context

        run_context = MagicMock()
        run_context.run_id = "timeout-test-run"

        # Must complete within 5 seconds (would hang indefinitely before fix)
        results = await asyncio.wait_for(
            asyncio.gather(
                tools.get_session_for_run(run_context=run_context),
                tools.get_session_for_run(run_context=run_context),
                tools.get_session_for_run(run_context=run_context),
            ),
            timeout=5.0,
        )

        assert len(results) == 3
        assert all(s is results[0] for s in results)


@pytest.mark.asyncio
async def test_mcp_tool_result_preserves_structured_content():
    mock_tool = MagicMock()
    mock_tool.name = "get_data"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[TextContent(type="text", text="hello")],
            is_error=False,
            structured_content={"id": "u1", "name": "Ada"},
        )
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert result.content == "hello"
    assert result.metadata["structured_content"] == {"id": "u1", "name": "Ada"}


@pytest.mark.asyncio
async def test_mcp_tool_result_uses_structured_content_when_content_is_empty():
    mock_tool = MagicMock()
    mock_tool.name = "get_data"
    structured_content = {"id": "u1", "name": "Ada", "role": "EMPLOYEE"}

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[],
            is_error=False,
            structured_content=structured_content,
        )
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert json.loads(result.content) == structured_content
    assert result.metadata["structured_content"] == structured_content


@pytest.mark.asyncio
async def test_mcp_tool_error_result_preserves_structured_content():
    mock_tool = MagicMock()
    mock_tool.name = "get_data"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[TextContent(type="text", text="upstream error")],
            is_error=True,
            structured_content={"error_details": {"code": 42}},
        )
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert "Error from MCP tool 'get_data'" in result.content
    assert result.metadata["structured_content"] == {"error_details": {"code": 42}}


@pytest.mark.asyncio
async def test_mcp_tool_result_handles_missing_structured_content_attr():
    # A result object with no structured_content attribute; the wrapper
    # must fall back to None instead of raising AttributeError.
    mock_tool = MagicMock()
    mock_tool.name = "get_data"

    result = MagicMock()
    result.is_error = False
    result.content = [TextContent(type="text", text="hello")]
    result.meta = None
    del result.structured_content

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(return_value=result)

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert result.content == "hello"
    # No _meta and no structured_content -> the envelope collapses to None.
    assert result.metadata is None


def test_tool_result_model_dump_roundtrip_preserves_structured_content():
    tool_result = ToolResult(content="hello", metadata={"structured_content": {"key": "value", "list": [1, 2, 3]}})
    payload = tool_result.model_dump()
    restored = ToolResult.model_validate(payload)
    assert restored.metadata["structured_content"] == {"key": "value", "list": [1, 2, 3]}


@pytest.mark.asyncio
async def test_mcp_tool_result_preserves_meta():
    mock_tool = MagicMock()
    mock_tool.name = "get_data"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[TextContent(type="text", text="hello")],
            is_error=False,
            _meta={"trace_id": "abc-123"},
        )
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert result.content == "hello"
    assert result.metadata == {"meta": {"trace_id": "abc-123"}}


@pytest.mark.asyncio
async def test_mcp_tool_error_result_preserves_meta():
    mock_tool = MagicMock()
    mock_tool.name = "get_data"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[TextContent(type="text", text="upstream error")],
            is_error=True,
            _meta={"trace_id": "err-456"},
        )
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert "Error from MCP tool 'get_data'" in result.content
    assert result.metadata == {"meta": {"trace_id": "err-456"}}


@pytest.mark.asyncio
async def test_mcp_tool_result_preserves_meta_and_structured_content():
    mock_tool = MagicMock()
    mock_tool.name = "get_data"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        return_value=CallToolResult(
            content=[TextContent(type="text", text="hello")],
            is_error=False,
            _meta={"trace_id": "abc-123"},
            structured_content={"id": "u1", "name": "Ada"},
        )
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    # Both sidecar values coexist under reserved keys in the single metadata envelope.
    assert result.metadata == {"meta": {"trace_id": "abc-123"}, "structured_content": {"id": "u1", "name": "Ada"}}


def test_tool_result_model_dump_roundtrip_preserves_metadata():
    tool_result = ToolResult(content="hello", metadata={"trace_id": "abc-123"})
    payload = tool_result.model_dump()
    restored = ToolResult.model_validate(payload)
    assert restored.metadata == {"trace_id": "abc-123"}


# =============================================================================
# Connection-failure error surfacing
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_tool_mcperror_returns_actionable_tool_result():
    """When the MCP server dies mid-call, call_tool raises MCPError. The wrapper
    must return a short, actionable ToolResult."""
    from mcp.shared.exceptions import MCPError

    mock_tool = MagicMock()
    mock_tool.name = "slow_tool"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(
        side_effect=MCPError(-32001, "Timed out while waiting for response to ClientRequest.")
    )

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert isinstance(result, ToolResult)
    assert "slow_tool" in result.content
    assert "MCP server may be unreachable" in result.content


@pytest.mark.asyncio
async def test_mcp_tool_cancelled_error_propagates():
    """CancelledError must propagate so cooperative cancellation still works."""
    mock_tool = MagicMock()
    mock_tool.name = "slow_tool"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(side_effect=asyncio.CancelledError())

    entrypoint = get_entrypoint_for_tool(mock_tool, session)

    with pytest.raises(asyncio.CancelledError):
        await entrypoint()


@pytest.mark.asyncio
async def test_mcp_tool_generic_exception_still_returns_tool_result():
    """Non-MCP, non-cancellation exceptions must be caught and surfaced
    as a ToolResult so the agent run loop keeps moving."""
    mock_tool = MagicMock()
    mock_tool.name = "flaky_tool"

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(side_effect=RuntimeError("something else broke"))

    entrypoint = get_entrypoint_for_tool(mock_tool, session)
    result = await entrypoint()

    assert isinstance(result, ToolResult)
    assert "something else broke" in result.content


# =============================================================================
# Tool-argument-name collision tests
# =============================================================================


def _make_mcp_tool_mock(name: str):
    """Build a minimal mock that quacks like mcp.types.Tool."""
    tool = MagicMock()
    tool.name = name
    return tool


def _make_session_returning(content_text: str):
    """Build a mock ClientSession whose call_tool returns a TextContent result."""
    from mcp.types import TextContent

    result = MagicMock()
    result.is_error = False
    result.content = [TextContent(type="text", text=content_text)]
    result.meta = None
    result.structured_content = None

    session = AsyncMock()
    session.send_ping = AsyncMock()
    session.call_tool = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_mcp_tool_with_team_argument_does_not_collide():
    """An MCP tool with a 'team' parameter must not collide with
    the framework's auto-injected `team` kwarg."""
    tool = _make_mcp_tool_mock("save_issue")
    session = _make_session_returning("issue saved")

    entrypoint = get_entrypoint_for_tool(tool, session)

    fn = Function(name="save_issue", entrypoint=entrypoint)
    fn._team = MagicMock(name="agno-team-instance")

    fc = FunctionCall(function=fn, arguments={"title": "Bug", "team": "Engineering"})

    result = await fc.aexecute()

    assert result.status == "success", f"Expected success, got error: {result.error}"
    session.call_tool.assert_awaited_once()
    called_name, called_kwargs = session.call_tool.await_args.args
    assert called_name == "save_issue"
    assert called_kwargs == {"title": "Bug", "team": "Engineering"}


@pytest.mark.asyncio
async def test_mcp_tool_with_agent_argument_does_not_collide():
    """An MCP tool with an 'agent' parameter must not collide
    with the framework's auto-injected `agent` kwarg."""
    tool = _make_mcp_tool_mock("assign_task")
    session = _make_session_returning("task assigned")

    entrypoint = get_entrypoint_for_tool(tool, session)

    fn = Function(name="assign_task", entrypoint=entrypoint)
    fn._agent = MagicMock(name="agno-agent-instance")

    fc = FunctionCall(function=fn, arguments={"task": "Fix bug", "agent": "alice"})

    result = await fc.aexecute()

    assert result.status == "success", f"Expected success, got error: {result.error}"
    called_name, called_kwargs = session.call_tool.await_args.args
    assert called_name == "assign_task"
    assert called_kwargs == {"task": "Fix bug", "agent": "alice"}


@pytest.mark.asyncio
async def test_mcp_tool_with_run_context_argument_does_not_collide():
    """An MCP tool with a 'run_context' parameter must not collide
    with the framework's auto-injected `run_context` kwarg."""
    tool = _make_mcp_tool_mock("log_event")
    session = _make_session_returning("logged")

    entrypoint = get_entrypoint_for_tool(tool, session)

    fn = Function(name="log_event", entrypoint=entrypoint)
    fn._run_context = MagicMock(name="agno-run-context")

    fc = FunctionCall(function=fn, arguments={"event": "click", "run_context": "from-llm"})

    result = await fc.aexecute()

    assert result.status == "success", f"Expected success, got error: {result.error}"
    called_name, called_kwargs = session.call_tool.await_args.args
    assert called_name == "log_event"
    assert called_kwargs == {"event": "click", "run_context": "from-llm"}


# =============================================================================
# tool_name pinning tests (security)
# =============================================================================


@pytest.mark.asyncio
async def test_model_supplied_tool_name_cannot_override_executed_tool():
    """A model-supplied tool_name argument must not change which tool the MCP
    server executes: the entrypoint is pinned to the tool it was built for."""
    tool = _make_mcp_tool_mock("list_issues")
    session = _make_session_returning("issues listed")

    entrypoint = get_entrypoint_for_tool(tool, session)
    await entrypoint(tool_name="delete_repo", repo="agno")

    session.call_tool.assert_awaited_once()
    called_name, called_kwargs = session.call_tool.await_args.args
    assert called_name == "list_issues"


@pytest.mark.asyncio
async def test_model_supplied_tool_name_is_forwarded_as_plain_argument():
    """tool_name has no special meaning to the entrypoint: it is forwarded to
    the server as an ordinary argument of the declared tool, so MCP tools that
    legitimately declare a tool_name parameter keep working."""
    tool = _make_mcp_tool_mock("call_helper")
    session = _make_session_returning("done")

    entrypoint = get_entrypoint_for_tool(tool, session)
    await entrypoint(tool_name="format_disk")

    called_name, called_kwargs = session.call_tool.await_args.args
    assert called_name == "call_helper"
    assert called_kwargs == {"tool_name": "format_disk"}


@pytest.mark.asyncio
async def test_function_call_arguments_cannot_override_executed_tool():
    """FunctionCall.aexecute merges model arguments into the entrypoint call;
    a smuggled tool_name must not change the executed tool on that path."""
    tool = _make_mcp_tool_mock("list_issues")
    session = _make_session_returning("issues listed")

    fn = Function(
        name="list_issues",
        entrypoint=get_entrypoint_for_tool(tool, session),
        skip_entrypoint_processing=True,
    )
    fc = FunctionCall(function=fn, arguments={"tool_name": "delete_repo", "repo": "agno"})

    result = await fc.aexecute()

    assert result.status == "success", f"Expected success, got error: {result.error}"
    session.call_tool.assert_awaited_once()
    called_name, called_kwargs = session.call_tool.await_args.args
    assert called_name == "list_issues"
    assert called_kwargs == {"tool_name": "delete_repo", "repo": "agno"}


@pytest.mark.asyncio
async def test_hitl_confirmation_gates_the_tool_that_executes():
    """requires_confirmation resolves from the Function's declared name, so the
    tool that executes must be that same name: calling an ungated tool with a
    smuggled tool_name must not reach the confirmation-gated tool."""
    session = _make_session_returning("ok")

    gated_fn = Function(
        name="delete_repo",
        entrypoint=get_entrypoint_for_tool(_make_mcp_tool_mock("delete_repo"), session),
        skip_entrypoint_processing=True,
        requires_confirmation=True,
    )
    ungated_fn = Function(
        name="list_issues",
        entrypoint=get_entrypoint_for_tool(_make_mcp_tool_mock("list_issues"), session),
        skip_entrypoint_processing=True,
        requires_confirmation=False,
    )

    # The model calls the unconfirmed tool but smuggles tool_name="delete_repo"
    fc = FunctionCall(function=ungated_fn, arguments={"tool_name": "delete_repo"})
    result = await fc.aexecute()

    assert result.status == "success", f"Expected success, got error: {result.error}"
    # Only the declared, unconfirmed tool reached the server; the gated tool
    # can only execute through its own Function, which pauses for confirmation.
    executed_names = [call.args[0] for call in session.call_tool.await_args_list]
    assert executed_names == ["list_issues"]
    assert gated_fn.requires_confirmation is True


# =============================================================================
# CancelledError propagation tests
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_is_alive_propagates_cancelled_error():
    """is_alive() must let CancelledError propagate, not convert it to False."""
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp")
    session = AsyncMock()
    session.send_ping = AsyncMock(side_effect=asyncio.CancelledError)
    tools.session = session

    with pytest.raises(asyncio.CancelledError):
        await tools.is_alive()


@pytest.mark.asyncio
async def test_mcp_is_alive_returns_false_on_ordinary_error():
    """An ordinary connection error during is_alive() is swallowed and returns False."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    session = AsyncMock()
    session.send_ping = AsyncMock(side_effect=ConnectionResetError("connection dropped"))
    tools.session = session

    assert await tools.is_alive() is False


@pytest.mark.asyncio
async def test_mcp_build_tools_propagates_cancelled_error():
    """build_tools() must let CancelledError propagate."""
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp")
    session = AsyncMock()
    session.list_tools = AsyncMock(side_effect=asyncio.CancelledError)
    tools.session = session

    with pytest.raises(asyncio.CancelledError):
        await tools.build_tools()


@pytest.mark.asyncio
async def test_mcp_initialize_propagates_cancelled_error():
    """initialize() must let CancelledError propagate."""
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp")
    session = AsyncMock()
    session.initialize = AsyncMock(side_effect=asyncio.CancelledError)
    tools.session = session

    with pytest.raises(asyncio.CancelledError):
        await tools.initialize()


@pytest.mark.asyncio
async def test_agent_refresh_propagates_cancelled_error_during_reconnect():
    """A CancelledError raised while reconnecting a refresh_connection MCP tool
    must propagate out of aget_tools so the run can be cancelled cleanly"""
    import asyncio
    from uuid import uuid4

    from agno.agent.agent import Agent
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    tools = MCPTools(url="http://localhost:8080/mcp", refresh_connection=True)
    tools.is_alive = AsyncMock(return_value=False)  # type: ignore[method-assign]
    tools.connect = AsyncMock(side_effect=asyncio.CancelledError)  # type: ignore[method-assign]

    agent = Agent(tools=[tools], telemetry=False)

    session_id = str(uuid4())
    run_id = str(uuid4())

    with pytest.raises(asyncio.CancelledError):
        await agent.aget_tools(
            session=AgentSession(session_id=session_id, session_data={}),
            run_response=RunOutput(run_id=run_id, session_id=session_id),
            run_context=RunContext(run_id=run_id, session_id=session_id),
        )


@pytest.mark.asyncio
async def test_agent_refresh_skips_tool_on_ordinary_error():
    """An ordinary connection error while refreshing a tool is logged and the
    run continues (graceful degradation)"""
    from uuid import uuid4

    from agno.agent.agent import Agent
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    tools = MCPTools(url="http://localhost:8080/mcp", refresh_connection=True)
    tools.is_alive = AsyncMock(return_value=False)  # type: ignore[method-assign]
    tools.connect = AsyncMock(side_effect=ConnectionRefusedError("server unreachable"))  # type: ignore[method-assign]

    agent = Agent(tools=[tools], telemetry=False)

    session_id = str(uuid4())
    run_id = str(uuid4())

    agent_tools = await agent.aget_tools(
        session=AgentSession(session_id=session_id, session_data={}),
        run_response=RunOutput(run_id=run_id, session_id=session_id),
        run_context=RunContext(run_id=run_id, session_id=session_id),
    )

    # Run completed despite the dead tool
    assert isinstance(agent_tools, list)


@pytest.mark.asyncio
async def test_agent_refresh_does_not_call_build_tools_after_reconnect():
    """When is_alive() is False, connect(force=True) reconnects.
    When the connection is alive, build_tools() is called to refresh definitions."""
    from uuid import uuid4

    from agno.agent.agent import Agent
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session.agent import AgentSession

    session_id = str(uuid4())
    run_id = str(uuid4())

    # Case 1: connection is dead -> reconnect, no separate build_tools()
    dead_tool = MCPTools(url="http://localhost:8080/mcp", refresh_connection=True)
    dead_tool.is_alive = AsyncMock(return_value=False)  # type: ignore[method-assign]
    dead_tool.connect = AsyncMock()  # type: ignore[method-assign]
    dead_tool.build_tools = AsyncMock()  # type: ignore[method-assign]

    await Agent(tools=[dead_tool], telemetry=False).aget_tools(
        session=AgentSession(session_id=session_id, session_data={}),
        run_response=RunOutput(run_id=run_id, session_id=session_id),
        run_context=RunContext(run_id=run_id, session_id=session_id),
        check_mcp_tools=False,
    )

    # Reconnected via connect(force=True); build_tools() not called separately
    dead_tool.connect.assert_any_await(force=True)
    dead_tool.build_tools.assert_not_awaited()

    # Case 2: connection is alive -> no reconnect, build_tools() refreshes definitions
    alive_tool = MCPTools(url="http://localhost:8080/mcp", refresh_connection=True)
    alive_tool.is_alive = AsyncMock(return_value=True)  # type: ignore[method-assign]
    alive_tool.connect = AsyncMock()  # type: ignore[method-assign]
    alive_tool.build_tools = AsyncMock()  # type: ignore[method-assign]

    await Agent(tools=[alive_tool], telemetry=False).aget_tools(
        session=AgentSession(session_id=session_id, session_data={}),
        run_response=RunOutput(run_id=run_id, session_id=session_id),
        run_context=RunContext(run_id=run_id, session_id=session_id),
        check_mcp_tools=False,
    )

    # No forced reconnect; build_tools() called to refresh definitions
    assert not any(call.kwargs.get("force") for call in alive_tool.connect.await_args_list)
    alive_tool.build_tools.assert_awaited_once()


# =============================================================================
# Cache identity tests (_agno_run_context channel)
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_cached_results_key_per_user_and_stay_per_run(tmp_path):
    """MCP entrypoints receive identity via _agno_run_context, so the cache
    keys per user. The injected object stays in the key material, so an MCP
    cache entry is scoped to its run: a header provider that reads the agent,
    the team, or run-context metadata cannot serve one caller's result to
    another."""
    from agno.run.base import RunContext

    tool = _make_mcp_tool_mock("get_data")
    session = _make_session_returning("payload")

    fn = Function(
        name="get_data",
        entrypoint=get_entrypoint_for_tool(tool, session),
        skip_entrypoint_processing=True,
        cache_results=True,
        cache_dir=str(tmp_path),
    )

    fn._run_context = RunContext(run_id="r1", session_id="s1", user_id="alice")
    await FunctionCall(function=fn).aexecute()

    # A different user must execute again, not be served alice's result
    fn._run_context = RunContext(run_id="r2", session_id="s2", user_id="bob")
    await FunctionCall(function=fn).aexecute()
    assert session.call_tool.await_count == 2

    # A new run executes again: the run's own context is part of the key
    fn._run_context = RunContext(run_id="r3", session_id="s1", user_id="alice")
    result = await FunctionCall(function=fn).aexecute()
    assert session.call_tool.await_count == 3
    assert result.status == "success"


@pytest.mark.asyncio
async def test_mcp_cached_hit_returns_tool_result(tmp_path):
    """A cache hit for an MCP tool must return a ToolResult, not the plain
    dict it was serialized to, so downstream result handling keeps working."""
    from agno.run.base import RunContext

    tool = _make_mcp_tool_mock("get_data")
    session = _make_session_returning("payload")

    fn = Function(
        name="get_data",
        entrypoint=get_entrypoint_for_tool(tool, session),
        skip_entrypoint_processing=True,
        cache_results=True,
        cache_dir=str(tmp_path),
    )
    fn._run_context = RunContext(run_id="r1", session_id="s1", user_id="alice")

    await FunctionCall(function=fn).aexecute()
    second = await FunctionCall(function=fn).aexecute()

    assert session.call_tool.await_count == 1
    assert isinstance(second.result, ToolResult)
    assert second.result.content == "payload"


# ----------------------------- _build_fastmcp_client -----------------------------


def test_build_fastmcp_client_puts_headers_on_the_transport():
    """Headers ride on the fastmcp transport, which is what reaches the server."""
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "streamable-http",
        {"url": "http://localhost:8080/mcp", "headers": {"Authorization": "Bearer t"}},
        None,
        10,
        "legacy",
    )

    assert client.transport.headers == {"Authorization": "Bearer t"}
    assert client.transport.url == "http://localhost:8080/mcp"


def test_build_fastmcp_client_defaults_to_the_legacy_protocol_era():
    """Legacy keeps the session-based era, so behaviour matches the pre-migration client."""
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client("streamable-http", {"url": "http://localhost:8080/mcp"}, None, 10, "legacy")

    assert client.mode == "legacy"


def test_build_fastmcp_client_honours_auto_mode():
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client("streamable-http", {"url": "http://localhost:8080/mcp"}, None, 10, "auto")

    assert client.mode == "auto"


def test_build_fastmcp_client_clamps_timeout_to_the_toolkit_limit():
    """The lower of the toolkit timeout and the params timeout wins, as before."""
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "streamable-http", {"url": "http://localhost:8080/mcp", "timeout": 60.0}, None, 10, "legacy"
    )

    # fastmcp hands the timeout to the session as read_timeout_seconds.
    assert client._session_kwargs["read_timeout_seconds"] == 10.0


def test_build_fastmcp_client_normalizes_a_timedelta_timeout():
    """A timedelta from an older config is accepted and converted to seconds."""
    from datetime import timedelta

    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "streamable-http",
        {"url": "http://localhost:8080/mcp", "timeout": timedelta(seconds=5)},
        None,
        10,
        "legacy",
    )

    assert client._session_kwargs["read_timeout_seconds"] == 5.0


def test_build_fastmcp_client_passes_sse_read_timeout_on_sse():
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "sse",
        {"url": "http://localhost:8080/sse", "sse_read_timeout": 120.0},
        None,
        10,
        "legacy",
    )

    # fastmcp normalizes the value to a timedelta on the transport.
    assert client.transport.sse_read_timeout.total_seconds() == 120.0


def test_build_fastmcp_client_builds_a_stdio_transport_from_server_params():
    """stdio carries no url or headers; the command comes off server_params."""
    from mcp import StdioServerParameters

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = StdioServerParameters(command="uvx", args=["some-server"], env={"A": "b"})
    client = _build_fastmcp_client("stdio", {}, params, 10, "legacy")

    assert client.transport.command == "uvx"
    assert client.transport.args == ["some-server"]
    assert client.transport.env == {"A": "b"}


@pytest.mark.asyncio
async def test_terminate_on_close_false_uses_the_forwarding_transport():
    """terminate_on_close=False must reach the SDK, not be silently dropped.

    fastmcp's stock StreamableHttpTransport omits the flag, so a caller asking to
    retain the server session would have it torn down anyway. The subclass forwards it.
    """
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "streamable-http",
        {"url": "http://localhost:8080/mcp", "terminate_on_close": False},
        None,
        10,
        "legacy",
    )

    assert client.transport._terminate_on_close is False
    assert type(client.transport).__name__ == "_RetainSessionTransport"


@pytest.mark.asyncio
async def test_terminate_on_close_none_still_retains_the_session():
    """Regression: StreamableHTTPClientParams defaults the field to None.

    The SDK gates its DELETE on ``session_id and terminate_on_close``, so None has
    always meant "keep the session". Treating None as True would silently start
    terminating sessions for every caller using the dataclass default.
    """
    from dataclasses import asdict

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = asdict(StreamableHTTPClientParams(url="http://localhost:8080/mcp"))
    assert params["terminate_on_close"] is None

    client = _build_fastmcp_client("streamable-http", params, None, 10, "legacy")

    assert type(client.transport).__name__ == "_RetainSessionTransport"
    assert client.transport._terminate_on_close is False


@pytest.mark.asyncio
async def test_terminate_on_close_true_stays_on_the_stock_transport():
    """The override is only taken when asked for; everyone else keeps fastmcp's own."""
    from fastmcp.client.transports import StreamableHttpTransport

    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "streamable-http", {"url": "http://localhost:8080/mcp", "terminate_on_close": True}, None, 10, "legacy"
    )
    assert type(client.transport) is StreamableHttpTransport


@pytest.mark.asyncio
async def test_terminate_on_close_transport_keeps_the_stream_read_timeout():
    """The subclass must not lose the httpx factory that bounds long-lived streams."""
    from dataclasses import asdict

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = asdict(StreamableHTTPClientParams(url="http://localhost:8080/mcp", terminate_on_close=False))
    client = _build_fastmcp_client("streamable-http", params, None, 10, "legacy")

    http_client = client.transport.httpx_client_factory(headers=None, auth=None)

    assert http_client.timeout.read == 300.0


@pytest.mark.asyncio
async def test_initialize_skips_the_handshake_for_a_fastmcp_client():
    """A fastmcp Client handshakes on entry; repeating it raises on the modern era.

    Regression: with protocol_mode="auto" the server negotiates the sessionless
    2026-07-28 era, where ``initialize`` has no InitializeResult and the SDK raises --
    which silently left the toolkit with zero registered tools.
    """
    from fastmcp import Client

    tools = MCPTools(url="http://localhost:8080/mcp", protocol_mode="auto")
    session = MagicMock(spec=Client)
    session.initialize = AsyncMock(side_effect=RuntimeError("modern era has no InitializeResult"))
    tools.session = session

    with patch.object(MCPTools, "build_tools", new=AsyncMock()):
        await tools.initialize()

    session.initialize.assert_not_awaited()
    assert tools._initialized is True


@pytest.mark.asyncio
async def test_initialize_still_handshakes_a_caller_supplied_session():
    """A ClientSession handed in by the caller has not been initialized for us."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    session = AsyncMock()
    tools.session = session

    with patch.object(MCPTools, "build_tools", new=AsyncMock()):
        await tools.initialize()

    session.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_ping_session_skips_the_probe_on_the_sessionless_era():
    """The 2026-07-28 era removed ping, so probing it would raise on every tool call."""
    from agno.utils.mcp import ping_session

    session = AsyncMock()
    session.protocol_version = "2026-07-28"

    await ping_session(session)

    session.ping.assert_not_awaited()
    session.send_ping.assert_not_awaited()


@pytest.mark.asyncio
async def test_ping_session_probes_on_the_session_based_era():
    from agno.utils.mcp import ping_session

    session = AsyncMock()
    session.protocol_version = "2025-11-25"
    del session.ping  # a ClientSession has send_ping, not ping

    await ping_session(session)

    session.send_ping.assert_awaited_once()


def test_build_fastmcp_client_keeps_sse_read_timeout_on_streamable_http():
    """Regression: the stream read must stay bounded by sse_read_timeout, not the
    session timeout.

    fastmcp derives its HTTP read timeout from read_timeout_seconds, so without a
    custom httpx factory a 10s session timeout would cut long-lived streams from
    300s down to 10s -- contradicting StreamableHTTPClientParams' documented contract.
    """
    from dataclasses import asdict

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = asdict(StreamableHTTPClientParams(url="http://localhost:8080/mcp"))
    client = _build_fastmcp_client("streamable-http", params, None, 10, "legacy")

    http_client = client.transport.httpx_client_factory(headers=None, auth=None)

    assert http_client.timeout.read == 300.0
    assert http_client.timeout.connect == 30.0


def test_build_fastmcp_client_maps_both_streamable_http_timeouts():
    """Each knob lands on its own axis: timeout on connect, sse_read_timeout on read."""
    from dataclasses import asdict

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = asdict(StreamableHTTPClientParams(url="http://localhost:8080/mcp", timeout=5, sse_read_timeout=600))
    client = _build_fastmcp_client("streamable-http", params, None, 10, "legacy")

    http_client = client.transport.httpx_client_factory(headers=None, auth=None)

    assert http_client.timeout.connect == 5.0
    assert http_client.timeout.read == 600.0


def test_build_fastmcp_client_normalizes_a_timedelta_sse_read_timeout():
    """A timedelta from an older config is accepted on the stream-read knob too."""
    from dataclasses import asdict
    from datetime import timedelta

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = asdict(StreamableHTTPClientParams(url="http://localhost:8080/mcp"))
    params["sse_read_timeout"] = timedelta(seconds=120)
    client = _build_fastmcp_client("streamable-http", params, None, 10, "legacy")

    http_client = client.transport.httpx_client_factory(headers=None, auth=None)

    assert http_client.timeout.read == 120.0


def test_both_session_types_satisfy_the_mcp_session_protocol():
    """MCPSession is what keeps the shared paths checked instead of falling back to Any.

    A connection is driven either by a fastmcp Client the toolkit built or by a
    ClientSession the caller supplied; the two are unrelated classes, so the structural
    type has to accept both or the annotations are a lie.
    """
    from fastmcp import Client
    from mcp import ClientSession

    from agno.utils.mcp import MCPSession

    assert isinstance(Client("http://localhost:8080/mcp"), MCPSession)
    assert issubclass(ClientSession, MCPSession)


def test_mcp_session_protocol_excludes_the_ping_methods():
    """ping is deliberately absent: the two types spell it differently.

    ClientSession has send_ping, fastmcp's Client has ping. Requiring either would
    exclude one of them, so ping_session resolves the name at its single call site.
    """
    from agno.utils.mcp import MCPSession

    assert not hasattr(MCPSession, "ping")
    assert not hasattr(MCPSession, "send_ping")


@pytest.mark.asyncio
async def test_failed_tool_call_returns_is_error_rather_than_raising():
    """A failing MCP tool is ordinary model-loop traffic, not an exception.

    fastmcp's Client defaults to raise_on_error=True, which would route failures through
    the generic handler: the result's meta/structured_content would be dropped and a
    stack trace logged for every failed call. Asking for is_error keeps the old path.
    """
    from fastmcp import Client
    from mcp.types import CallToolResult, TextContent

    from agno.utils.mcp import get_entrypoint_for_tool

    failure = CallToolResult(content=[TextContent(type="text", text="boom")], isError=True)
    session = MagicMock(spec=Client)
    session.call_tool = AsyncMock(return_value=failure)
    session.protocol_version = "2025-11-25"

    entrypoint = get_entrypoint_for_tool(_make_mcp_tool_mock("boom"), session)
    result = await entrypoint()

    assert session.call_tool.await_args.kwargs["raise_on_error"] is False
    assert "Error from MCP tool 'boom'" in result.content


@pytest.mark.asyncio
async def test_client_session_call_tool_is_not_given_raise_on_error():
    """A caller-supplied ClientSession has no such kwarg and would reject it."""
    from mcp.types import CallToolResult, TextContent

    from agno.utils.mcp import get_entrypoint_for_tool

    ok = CallToolResult(content=[TextContent(type="text", text="fine")], isError=False)
    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=ok)
    session.protocol_version = "2025-11-25"

    entrypoint = get_entrypoint_for_tool(_make_mcp_tool_mock("ok"), session)
    await entrypoint()

    assert "raise_on_error" not in (session.call_tool.await_args.kwargs or {})


def test_build_fastmcp_client_maps_both_sse_timeouts():
    """SSE keeps connect/write and stream-read on separate axes, as streamable-http does."""
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "sse", {"url": "http://localhost:8080/sse", "timeout": 5, "sse_read_timeout": 600}, None, 10, "legacy"
    )

    http_client = client.transport.httpx_client_factory(headers=None, auth=None)

    assert http_client.timeout.connect == 5.0
    assert http_client.timeout.read == 600.0


def test_missing_fastmcp_raises_an_install_hint():
    """connect() swallows exceptions, so an unguarded ModuleNotFoundError would surface
    only as an agent running with zero tools. The guard names the missing extra the way
    the mcp import guard does."""
    import builtins

    from agno.tools.mcp.mcp import _import_fastmcp

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "fastmcp" or name.startswith("fastmcp."):
            raise ModuleNotFoundError("No module named 'fastmcp'")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", blocked):
        with pytest.raises(ImportError, match=r"fastmcp.*not installed"):
            _import_fastmcp()


def test_stdio_transport_does_not_keep_the_subprocess_alive():
    """close() must stop the stdio server process.

    fastmcp's StdioTransport defaults keep_alive to True, which would leave one orphaned
    child per connect/close cycle -- and a non-AgentOS agent run does one cycle per run.
    """
    from mcp import StdioServerParameters

    from agno.tools.mcp.mcp import _build_fastmcp_client

    params = StdioServerParameters(command="echo", args=["hi"], env=None)
    client = _build_fastmcp_client("stdio", {}, params, 10, "legacy")

    assert client.transport.keep_alive is False


@pytest.mark.asyncio
async def test_retain_session_transport_captures_the_session_id():
    """The custom transport must record mcp-session-id like fastmcp's own does.

    The SDK's client no longer surfaces the id, so both transports read it off the
    response headers. Without it the tool-call trace spans lose the identifier on every
    server_params connection, which is the default path.
    """
    from agno.tools.mcp.mcp import _build_fastmcp_client

    client = _build_fastmcp_client(
        "streamable-http",
        {"url": "http://localhost:8080/mcp", "terminate_on_close": False},
        None,
        10,
        "legacy",
    )
    transport = client.transport

    assert transport.get_session_id() is None

    response = MagicMock()
    response.headers = {"mcp-session-id": "abc123"}
    await transport._capture_session_id(response)

    assert transport.get_session_id() == "abc123"
