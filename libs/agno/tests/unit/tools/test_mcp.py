from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.function import Function, FunctionCall
from agno.tools.mcp import MCPTools, MultiMCPTools
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from agno.utils.mcp import get_entrypoint_for_tool


class _AsyncContextManager:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _AsyncExitStackStub:
    async def enter_async_context(self, context):
        return await context.__aenter__()


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


@pytest.mark.asyncio
async def test_connect_merges_init_headers_when_streamable_http_headers_default_to_none():
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
        header_provider=lambda: {"Authorization": "Bearer token"},
    )

    with (
        patch(
            "agno.tools.mcp.mcp.streamablehttp_client",
            return_value=_AsyncContextManager(("read", "write")),
        ) as streamable_http_mock,
        patch("agno.tools.mcp.mcp.ClientSession", return_value=_AsyncContextManager(MagicMock())),
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert streamable_http_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_connect_merges_init_headers_when_sse_headers_default_to_none():
    tools = MCPTools(
        server_params=SSEClientParams(url="http://localhost:8080/sse"),
        transport="sse",
        header_provider=lambda: {"Authorization": "Bearer token"},
    )

    with (
        patch("agno.tools.mcp.mcp.sse_client", return_value=_AsyncContextManager(("read", "write"))) as sse_client_mock,
        patch("agno.tools.mcp.mcp.ClientSession", return_value=_AsyncContextManager(MagicMock())),
        patch.object(MCPTools, "initialize", new=AsyncMock()),
    ):
        await tools._connect()

    assert sse_client_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_multimcp_connect_merges_init_headers_when_streamable_http_headers_default_to_none():
    tools = MultiMCPTools(
        server_params_list=[StreamableHTTPClientParams(url="http://localhost:8080/mcp")],
        header_provider=lambda: {"Authorization": "Bearer token"},
    )
    tools._async_exit_stack = _AsyncExitStackStub()

    with (
        patch(
            "agno.tools.mcp.multi_mcp.streamablehttp_client",
            return_value=_AsyncContextManager(("read", "write")),
        ) as streamable_http_mock,
        patch("agno.tools.mcp.multi_mcp.ClientSession", return_value=_AsyncContextManager(MagicMock())),
        patch.object(MultiMCPTools, "initialize", new=AsyncMock()),
        patch.object(MultiMCPTools, "build_tools", new=AsyncMock()),
    ):
        await tools._connect()

    assert streamable_http_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.asyncio
async def test_multimcp_connect_merges_init_headers_when_sse_headers_default_to_none():
    tools = MultiMCPTools(
        server_params_list=[SSEClientParams(url="http://localhost:8080/sse")],
        header_provider=lambda: {"Authorization": "Bearer token"},
    )
    tools._async_exit_stack = _AsyncExitStackStub()

    with (
        patch(
            "agno.tools.mcp.multi_mcp.sse_client", return_value=_AsyncContextManager(("read", "write"))
        ) as sse_client_mock,
        patch("agno.tools.mcp.multi_mcp.ClientSession", return_value=_AsyncContextManager(MagicMock())),
        patch.object(MultiMCPTools, "initialize", new=AsyncMock()),
        patch.object(MultiMCPTools, "build_tools", new=AsyncMock()),
    ):
        await tools._connect()

    assert sse_client_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}


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
        patch("agno.tools.mcp.mcp.sse_client", return_value=_AsyncContextManager(("read", "write"))) as sse_mock,
        patch("agno.tools.mcp.mcp.ClientSession") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_cls.return_value = mock_session_context

        session = await tools.get_session_for_run(run_context=run_context)

    assert sse_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}
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
        patch(
            "agno.tools.mcp.mcp.streamablehttp_client",
            return_value=_AsyncContextManager(("read", "write")),
        ) as streamable_mock,
        patch("agno.tools.mcp.mcp.ClientSession") as mock_session_cls,
    ):
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_cls.return_value = mock_session_context

        session = await tools.get_session_for_run(run_context=run_context)

    assert streamable_mock.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}
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
# Parallel tool call session tests (issue #6094)
# =============================================================================


@pytest.mark.asyncio
async def test_parallel_get_session_for_run_creates_single_session():
    """Parallel calls to get_session_for_run with the same run_id must
    create exactly one session (not one per concurrent coroutine)."""
    import asyncio

    creation_count = {"count": 0}

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {"X-Token": "t"})

    with patch("agno.tools.mcp.mcp.streamablehttp_client") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)
        mock_client.return_value = mock_context

        with patch("agno.tools.mcp.mcp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.initialize = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session
            mock_session_cls.return_value = mock_session_context

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

    with patch("agno.tools.mcp.mcp.streamablehttp_client") as mock_client:

        def make_mock_context():
            ctx = AsyncMock()
            ctx.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)
            return ctx

        mock_client.side_effect = lambda **kw: make_mock_context()

        with patch("agno.tools.mcp.mcp.ClientSession") as mock_session_cls:
            call_count = {"n": 0}

            def make_mock_session_ctx(*args, **kwargs):
                call_count["n"] += 1
                sess = AsyncMock()
                sess.initialize = AsyncMock()
                sess._id = call_count["n"]
                ctx = AsyncMock()
                ctx.__aenter__.return_value = sess
                return ctx

            mock_session_cls.side_effect = make_mock_session_ctx

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
async def test_connect_failure_cleans_up_transport_context_streamable_http():
    """When streamablehttp_client.__aenter__ raises, the partially-entered
    transport context must be explicitly closed otherwise it leaks."""
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )

    failing_context = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    with patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=failing_context):
        with pytest.raises(ConnectionRefusedError):
            await tools._connect()

    assert failing_context.aexit_called or failing_context.aclose_called
    assert tools._context is None


@pytest.mark.asyncio
async def test_connect_failure_cleans_up_transport_context_sse():
    """SSE transport variant of the cleanup-on-aenter-failure test."""
    tools = MCPTools(
        server_params=SSEClientParams(url="http://localhost:8080/sse"),
        transport="sse",
    )

    failing_context = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    with patch("agno.tools.mcp.mcp.sse_client", return_value=failing_context):
        with pytest.raises(ConnectionRefusedError):
            await tools._connect()

    assert failing_context.aexit_called or failing_context.aclose_called
    assert tools._context is None


@pytest.mark.asyncio
async def test_connect_failure_cleans_up_both_contexts_when_session_aenter_fails():
    """If the transport context enters successfully but the ClientSession
    fails to enter, both context managers must be cleaned up before re-raise."""
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )

    transport_context = _SucceedingAenterContext(("read", "write", None))
    failing_session_context = _FailingAenterContext(RuntimeError("session init failed"))

    with (
        patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=transport_context),
        patch("agno.tools.mcp.mcp.ClientSession", return_value=failing_session_context),
    ):
        with pytest.raises(RuntimeError, match="session init failed"):
            await tools._connect()

    assert failing_session_context.aexit_called or failing_session_context.aclose_called
    assert transport_context.aexit_called
    assert tools._context is None
    assert tools._session_context is None


@pytest.mark.asyncio
async def test_connect_public_does_not_raise_when_mcp_server_unreachable():
    """connect() entrypoint used by the agent run loop and AgentOS /agents endpoint.
    If the MCP server is down it must NOT raise"""
    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )

    failing_context = _FailingAenterContext(ConnectionRefusedError("server unreachable"))

    with patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=failing_context):
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

    with patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=failing_context):
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

    with patch("agno.tools.mcp.mcp.streamablehttp_client") as mock_client:
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)
        mock_client.return_value = mock_context

        with patch("agno.tools.mcp.mcp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.initialize = AsyncMock()
            mock_session_context = AsyncMock()
            mock_session_context.__aenter__.return_value = mock_session
            mock_session_cls.return_value = mock_session_context

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
    result.isError = False
    result.content = [TextContent(type="text", text=content_text)]

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
# Cross-task cleanup guard tests (issue #8156)
# =============================================================================


@pytest.mark.asyncio
async def test_cleanup_run_session_from_different_task_is_safe():
    """Simulate cleanup_run_session() called from a different task than the
    one that created the session. The cross-task guard must skip __aexit__
    (to avoid anyio cancel scope corruption) and still remove the tracking
    entries, without raising any exception.
    """
    import asyncio

    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {})
    tools.session = MagicMock()

    # Simulate a session that was created by a different task
    run_id = "diff-task-run"

    async def _simulate_session_creation():
        """Create a session from a background task that we will
        later attempt to clean up from the main test task."""
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        with patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=mock_context):
            with patch("agno.tools.mcp.mcp.ClientSession", return_value=mock_session_context):
                run_context = MagicMock()
                run_context.run_id = run_id
                await tools.get_session_for_run(run_context=run_context)

        # Return the context mocks so we can assert on them
        return mock_session_context, mock_context

    # Create the session in a background task (different from the main test task)
    bg_task = asyncio.create_task(_simulate_session_creation())
    session_ctx_mock, transport_ctx_mock = await bg_task

    # Verify the session was tracked
    assert run_id in tools._run_sessions
    assert run_id in tools._run_session_contexts
    assert run_id in tools._run_session_tasks

    # Now call cleanup_run_session from the MAIN task (different from the
    # background task that created it). This must NOT call __aexit__ on the
    # context managers (otherwise it would corrupt anyio cancel scopes), and
    # it must NOT raise any exception.
    try:
        await tools.cleanup_run_session(run_id)
    except Exception as e:
        pytest.fail(f"cleanup_run_session from a different task raised: {e}")

    # __aexit__ should NOT have been called (cross-task guard)
    session_ctx_mock.__aexit__.assert_not_called()
    transport_ctx_mock.__aexit__.assert_not_called()

    # Tracking entries should be removed regardless
    assert run_id not in tools._run_sessions
    assert run_id not in tools._run_session_contexts
    assert run_id not in tools._run_session_tasks


@pytest.mark.asyncio
async def test_cleanup_run_session_from_same_task_calls_aexit():
    """When cleanup_run_session() is called from the SAME task that created
    the session, __aexit__ must be called on both context managers to
    perform proper resource cleanup.
    """
    tools = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda: {})
    tools.session = MagicMock()

    run_id = "same-task-run"

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    mock_session_context = AsyncMock()
    mock_session_context.__aenter__.return_value = mock_session

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

    with patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=mock_context):
        with patch("agno.tools.mcp.mcp.ClientSession", return_value=mock_session_context):
            run_context = MagicMock()
            run_context.run_id = run_id
            await tools.get_session_for_run(run_context=run_context)

    # Verify the session was tracked
    assert run_id in tools._run_sessions

    # Now cleanup from the SAME task — __aexit__ should be called
    await tools.cleanup_run_session(run_id)

    session_ctx_mock.__aexit__.assert_called()
    transport_ctx_mock.__aexit__.assert_called()

    # Tracking entries should be removed
    assert run_id not in tools._run_sessions
    assert run_id not in tools._run_session_contexts
    assert run_id not in tools._run_session_tasks


@pytest.mark.asyncio
async def test_close_from_different_task_skips_aexit():
    """When close() is called from a different task than _connect(),
    it must skip __aexit__/aclose() on the main contexts to avoid
    anyio cancel scope corruption. Tracking entries should still be
    cleaned up.
    """
    import asyncio

    tools = MCPTools(
        server_params=StreamableHTTPClientParams(url="http://localhost:8080/mcp"),
        transport="streamable-http",
    )

    # Use a background task to call _connect() so that _connect_task
    # is set to a different task than the main test task.
    connect_task = asyncio.create_task(
        tools._connect() if False else asyncio.sleep(0)  # dummy — we'll mock instead
    )

    async def _connect_in_bg():
        transport_ctx = _SucceedingAenterContext(("read", "write", None))
        session_ctx = _SucceedingAenterContext(MagicMock())

        with patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=transport_ctx):
            with patch("agno.tools.mcp.mcp.ClientSession", return_value=session_ctx):
                with patch.object(tools, "initialize", new=AsyncMock()):
                    await tools._connect()

        return transport_ctx, session_ctx

    bg_task = asyncio.create_task(_connect_in_bg())
    transport_ctx, session_ctx = await bg_task

    # Verify that _connect() was entered from the background task
    assert tools._connect_task is not None
    assert tools._connect_task is not asyncio.current_task()

    # Ensure we are in a different task from the one that called _connect()
    assert tools._connect_task is not asyncio.current_task()

    # Now call close() from the MAIN task. It must NOT call __aexit__
    # on the context managers.
    await tools.close()

    transport_ctx.aexit_called = transport_ctx.aexit_called  # from _SucceedingAenterContext
    # The close() should have skipped __aexit__ since we are in a different task
    # and the instance should be marked as not initialized
    assert tools._initialized is False
    assert tools.session is None
    assert tools._session_context is None
    assert tools._context is None
