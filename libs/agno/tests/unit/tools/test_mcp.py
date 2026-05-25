from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams


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
# Lifecycle lock tests (parallel connect/close race — issue #8013, related #7347)
# =============================================================================


def _make_concurrency_tool() -> MCPTools:
    """MCPTools instance configured for the lifecycle-lock concurrency tests.

    Uses streamable-http with explicit server_params so construction succeeds
    without hitting any real network — every test below stubs ``_connect`` /
    ``_close_locked`` so we exercise lock semantics in isolation.
    """
    from datetime import timedelta

    return MCPTools(
        url="http://example.test/mcp",
        transport="streamable-http",
        server_params=StreamableHTTPClientParams(
            url="http://example.test/mcp",
            headers=None,
            timeout=timedelta(seconds=300),
        ),
        timeout_seconds=300,
    )


@pytest.mark.asyncio
async def test_parallel_connect_runs_underlying_connect_exactly_once(monkeypatch):
    """Five concurrent ``connect()`` callers must share a single underlying
    ``_connect()`` invocation. Without the lifecycle lock all five would race
    past the ``not _initialized`` check and each open its own MCP session,
    leaving four orphans whose backing tasks tear down their anyio streams
    when GC'd — the ``BrokenResourceError`` the lock is here to prevent.
    """
    import asyncio

    tool = _make_concurrency_tool()

    call_count = 0
    inflight = 0
    max_inflight = 0

    async def fake_connect(self):
        nonlocal call_count, inflight, max_inflight
        call_count += 1
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        try:
            # Yield to the loop so any racing caller has a real chance to
            # observe overlap if the lock were missing.
            await asyncio.sleep(0.01)
            self._initialized = True
        finally:
            inflight -= 1

    monkeypatch.setattr(MCPTools, "_connect", fake_connect)

    await asyncio.gather(*(tool.connect() for _ in range(5)))

    assert call_count == 1, (
        f"_connect() ran {call_count} times under parallel callers; "
        "the lifecycle lock + double-check should serialize them to one."
    )
    assert max_inflight == 1, (
        "two _connect() calls were in flight simultaneously — the lifecycle lock is not actually serializing them."
    )
    assert tool.initialized is True


@pytest.mark.asyncio
async def test_connect_fast_path_skips_lock_when_already_initialized(monkeypatch):
    """Once initialized, ``connect()`` must not even acquire the lock — the
    hot agent-run path calls ``connect()`` on every run and must not pay a
    serialization cost when there is nothing to do.
    """
    import asyncio

    tool = _make_concurrency_tool()

    async def fake_connect(self):
        self._initialized = True

    monkeypatch.setattr(MCPTools, "_connect", fake_connect)

    await tool.connect()
    assert tool.initialized is True

    # Hold the lifecycle lock externally to prove that the second connect()
    # call takes the lock-free fast path. If it tries to acquire the lock,
    # the wait_for() below times out and the test fails loudly.
    lock = tool._lifecycle_lock  # noqa: SLF001 — white-box concurrency probe
    assert not lock.locked()

    await lock.acquire()
    try:
        # If the fast path is broken, this hangs until the timeout — guard
        # with a short timeout so the test fails loudly instead of stalling.
        await asyncio.wait_for(tool.connect(), timeout=0.1)
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_close_waits_for_inflight_connect(monkeypatch):
    """A ``close()`` racing an in-flight ``connect()`` must wait for the
    connect to finish before tearing down. Otherwise close can strand a
    session another caller is in the middle of bringing up.
    """
    import asyncio

    tool = _make_concurrency_tool()

    connect_started = asyncio.Event()
    release_connect = asyncio.Event()
    close_ran_at: list[float] = []

    async def fake_connect(self):
        connect_started.set()
        await release_connect.wait()
        self._initialized = True

    async def fake_close_locked(self):
        # Record observation order; assert below that this only ran after
        # connect completed.
        close_ran_at.append(asyncio.get_event_loop().time())
        self._initialized = False

    monkeypatch.setattr(MCPTools, "_connect", fake_connect)
    monkeypatch.setattr(MCPTools, "_close_locked", fake_close_locked)

    connect_task = asyncio.create_task(tool.connect())
    await connect_started.wait()

    close_task = asyncio.create_task(tool.close())

    # Give the close task a chance to wake up and try to acquire the lock.
    await asyncio.sleep(0.02)
    assert not close_task.done(), (
        "close() returned before connect() released the lock — lifecycle lock is not serializing them."
    )
    assert close_ran_at == [], "close body ran while connect was in flight"

    # Now release connect; close should proceed.
    release_connect.set()
    await asyncio.wait_for(connect_task, timeout=1.0)
    await asyncio.wait_for(close_task, timeout=1.0)

    assert len(close_ran_at) == 1
    assert tool.initialized is False


@pytest.mark.asyncio
async def test_connect_force_true_does_not_deadlock(monkeypatch):
    """``connect(force=True)`` tears down the existing session before
    reconnecting. It does so from *inside* ``_lifecycle_lock`` by calling
    ``_close_locked()`` directly — calling the public ``close()`` here would
    re-acquire the same lock and deadlock. This test guards against the
    refactor regressing to the wrong call.
    """
    import asyncio

    tool = _make_concurrency_tool()

    connect_calls = 0
    close_calls = 0

    async def fake_connect(self):
        nonlocal connect_calls
        connect_calls += 1
        self._initialized = True

    async def fake_close_locked(self):
        nonlocal close_calls
        close_calls += 1
        self._initialized = False

    monkeypatch.setattr(MCPTools, "_connect", fake_connect)
    monkeypatch.setattr(MCPTools, "_close_locked", fake_close_locked)

    await tool.connect()
    assert connect_calls == 1
    assert close_calls == 0

    # Short timeout so a self-deadlock fails loudly rather than hanging CI.
    await asyncio.wait_for(tool.connect(force=True), timeout=1.0)

    assert close_calls == 1, "force=True did not tear down the prior session"
    assert connect_calls == 2, "force=True did not reconnect after close"
    assert tool.initialized is True


@pytest.mark.asyncio
async def test_aenter_propagates_connect_failure(monkeypatch):
    """``async with MCPTools(...) as tool:`` must raise when the underlying
    ``_connect()`` fails (network down, 401 from MCP middleware, handshake
    error). Going through the public ``connect()`` — whose ``try/except``
    intentionally swallows for the ``pre_run_hook`` path — would leave the
    caller with an uninitialized ``tool`` and a confusing ``NoneType`` error
    on the next call instead of a clean failure at the ``async with``
    boundary. This guards the ``__aenter__`` → ``_connect()`` (direct) wiring
    against accidentally being refactored back to ``__aenter__`` →
    ``connect()``.
    """

    tool = _make_concurrency_tool()

    class BoomError(RuntimeError):
        pass

    async def fake_connect(self):
        raise BoomError("simulated MCP handshake failure")

    monkeypatch.setattr(MCPTools, "_connect", fake_connect)

    with pytest.raises(BoomError, match="simulated MCP handshake failure"):
        async with tool:
            pytest.fail("entered async-with body despite _connect() failure")

    assert tool.initialized is False
    # Lock must be released even after the failure so retries / close()
    # don't deadlock.
    assert not tool._lifecycle_lock.locked()  # noqa: SLF001


@pytest.mark.asyncio
async def test_connect_method_still_swallows_failures(monkeypatch):
    """Companion guard for the test above: the public ``connect()`` must
    keep its log-and-continue contract so ``pre_run_hook`` can iterate
    every MCP tool on an agent and let unrelated tools continue working
    even if one server is down. If this regresses to re-raising,
    ``pre_run_hook`` would abort the whole agent run on the first bad MCP.
    """

    tool = _make_concurrency_tool()

    async def fake_connect(self):
        raise RuntimeError("simulated handshake failure")

    monkeypatch.setattr(MCPTools, "_connect", fake_connect)

    await tool.connect()

    assert tool.initialized is False
    assert not tool._lifecycle_lock.locked()  # noqa: SLF001


@pytest.mark.asyncio
async def test_lifecycle_lock_is_lazy_and_stable():
    """The lifecycle lock must be lazily constructed on first access and
    return the same instance thereafter. Lazy because constructing it in
    ``__init__`` would bind it to whichever event loop happened to be
    running at construction time, which is often not the one running the
    agent.
    """
    import asyncio

    tool = _make_concurrency_tool()

    assert tool._lifecycle_lock_inst is None  # noqa: SLF001

    lock = tool._lifecycle_lock  # noqa: SLF001
    assert isinstance(lock, asyncio.Lock)
    # Subsequent access returns the same lock instance.
    assert tool._lifecycle_lock is lock  # noqa: SLF001
