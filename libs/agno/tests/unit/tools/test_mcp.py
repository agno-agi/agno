from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools
from agno.tools.mcp.params import StreamableHTTPClientParams


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


@pytest.mark.asyncio
async def test_multimcp_without_endpoints():
    """Test that ValueError is raised when no endpoints are provided."""
    with pytest.raises(ValueError, match="Either server_params_list or commands or urls must be provided"):
        async with MultiMCPTools():
            pass


def test_multimcp_empty_command_string():
    """Test that ValueError is raised when a command string is empty."""
    with pytest.raises(ValueError, match="MCP command can't be empty"):
        # Mock shlex.split to return an empty list
        with patch("shlex.split", return_value=[]):
            MultiMCPTools(commands=[""])


def test_url_defaults_to_streamable_http_transport():
    """Test that transport defaults to streamable-http when url is provided."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    assert tools.transport == "streamable-http"


def test_stdio_transport_with_url_overrides_to_streamable_http():
    """Test that stdio transport gets overridden to streamable-http when url is present."""
    tools = MCPTools(url="http://localhost:8080/mcp", transport="stdio")
    assert tools.transport == "streamable-http"


def test_multimcp_urls_default_to_streamable_http():
    """Test that MultiMCPTools defaults to streamable-http when urls are provided without urls_transports."""
    tools = MultiMCPTools(urls=["http://localhost:8080/mcp", "http://localhost:8081/mcp"])
    assert len(tools.server_params_list) == 2
    assert all(isinstance(params, StreamableHTTPClientParams) for params in tools.server_params_list)


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

    # Simulate an old session from a previous run
    old_session = MagicMock()
    old_context = MagicMock()
    old_session_context = MagicMock()
    tools._run_sessions["old-run-id"] = (old_session, time.time() - 1.0)  # 1 second ago
    tools._run_session_contexts["old-run-id"] = (old_context, old_session_context)

    # Wait for TTL to expire
    time.sleep(0.15)

    # Now simulate a new run requesting a session - this should trigger cleanup
    # We need to mock the session creation since we don't have a real MCP server
    with patch("agno.tools.mcp.mcp.streamablehttp_client") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)
        mock_client.return_value = mock_context

        with patch("agno.tools.mcp.mcp.ClientSession") as mock_session_cls:
            mock_new_session = AsyncMock()
            mock_new_session.initialize = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_new_session
            mock_session_cls.return_value = mock_session_context

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
        mock_tool.inputSchema = {"type": "object", "properties": {}}
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
    mock_tool.inputSchema = {"type": "object", "properties": {}}

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
# load_server_instructions tests (feat: load server instructions from MCP InitializeResult)
# =============================================================================


def test_load_server_instructions_defaults_to_true():
    """Test that load_server_instructions defaults to True."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    assert tools.load_server_instructions is True


def test_load_server_instructions_can_be_disabled():
    """Test that load_server_instructions can be set to False."""
    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=False)
    assert tools.load_server_instructions is False


@pytest.mark.asyncio
async def test_initialize_sets_instructions_from_init_result():
    """Test that initialize() captures instructions from InitializeResult when load_server_instructions=True."""
    server_instructions = "Use this server to search for files. Always provide absolute paths."

    mock_init_result = MagicMock()
    mock_init_result.instructions = server_instructions

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=mock_init_result)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session

    await tools.initialize()

    assert tools.instructions == server_instructions


@pytest.mark.asyncio
async def test_initialize_skips_instructions_when_disabled():
    """Test that initialize() does NOT set instructions when load_server_instructions=False."""
    server_instructions = "Use this server to search for files."

    mock_init_result = MagicMock()
    mock_init_result.instructions = server_instructions

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=mock_init_result)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=False)
    tools.session = mock_session
    # Ensure instructions are not pre-set
    tools.instructions = None

    await tools.initialize()

    assert tools.instructions is None


@pytest.mark.asyncio
async def test_initialize_handles_none_init_result_gracefully():
    """Test that initialize() handles None InitializeResult without raising an error."""
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=None)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session
    tools.instructions = None

    # Should not raise
    await tools.initialize()

    # instructions should remain None (no InitializeResult to read from)
    assert tools.instructions is None


@pytest.mark.asyncio
async def test_initialize_handles_init_result_without_instructions_field():
    """Test that initialize() handles an InitializeResult that has no 'instructions' attribute."""
    mock_init_result = MagicMock(spec=[])  # spec=[] means no attributes allowed

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=mock_init_result)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session
    tools.instructions = None

    # Should not raise even when instructions attribute doesn't exist
    await tools.initialize()

    assert tools.instructions is None


@pytest.mark.asyncio
async def test_initialize_handles_init_result_with_none_instructions():
    """Test that initialize() does not override instructions when InitializeResult.instructions is None."""
    mock_init_result = MagicMock()
    mock_init_result.instructions = None  # Server returned no instructions

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=mock_init_result)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session
    tools.instructions = None

    await tools.initialize()

    # instructions should remain None; None instructions from server shouldn't override
    assert tools.instructions is None


@pytest.mark.asyncio
async def test_initialize_handles_init_result_with_empty_string_instructions():
    """Test that initialize() does not set instructions when InitializeResult.instructions is empty string."""
    mock_init_result = MagicMock()
    mock_init_result.instructions = ""  # Empty string is falsy

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=mock_init_result)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session
    tools.instructions = None

    await tools.initialize()

    # Empty string is falsy, so instructions should remain None
    assert tools.instructions is None


@pytest.mark.asyncio
async def test_initialize_idempotent_does_not_overwrite_instructions():
    """Test that calling initialize() twice does not re-run (idempotency via _initialized flag)."""
    server_instructions = "Server-provided usage guidelines."

    mock_init_result = MagicMock()
    mock_init_result.instructions = server_instructions

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(return_value=mock_init_result)
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session

    await tools.initialize()
    assert tools.instructions == server_instructions

    # Change what session.initialize returns to simulate a different result
    mock_init_result2 = MagicMock()
    mock_init_result2.instructions = "DIFFERENT INSTRUCTIONS"
    mock_session.initialize = AsyncMock(return_value=mock_init_result2)

    # Second call should be a no-op due to _initialized flag
    await tools.initialize()

    # Instructions should still be the original ones
    assert tools.instructions == server_instructions
    # session.initialize should only have been called once total
    assert mock_session.initialize.call_count == 0  # reset mock, was not called again


@pytest.mark.asyncio
async def test_initialize_instructions_available_after_build_tools():
    """Test that instructions are set BEFORE build_tools() is called during initialize()."""
    set_order = []

    server_instructions = "Always authenticate before calling tools."

    mock_init_result = MagicMock()
    mock_init_result.instructions = server_instructions

    async def fake_initialize():
        return mock_init_result

    async def fake_list_tools():
        # At this point, instructions should already be set (initialize sets them before build_tools)
        set_order.append(("list_tools_called", tools.instructions))
        return MagicMock(tools=[])

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(side_effect=fake_initialize)
    mock_session.list_tools = AsyncMock(side_effect=fake_list_tools)

    tools = MCPTools(url="http://localhost:8080/mcp", load_server_instructions=True)
    tools.session = mock_session

    await tools.initialize()

    # By the time list_tools was called, instructions should have been set
    assert len(set_order) == 1
    assert set_order[0][1] == server_instructions
    assert tools.instructions == server_instructions
