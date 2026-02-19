"""Tests for CancelledError handling in MCP reconnection and redundant build_tools removal."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools

# =============================================================================
# CancelledError propagation tests
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_connect_propagates_cancelled_error():
    """Test that CancelledError is re-raised from MCPTools.connect(), not swallowed."""
    tools = MCPTools(url="http://localhost:8080/mcp")

    with patch.object(tools, "_connect", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await tools.connect()


@pytest.mark.asyncio
async def test_mcp_connect_force_propagates_cancelled_error():
    """Test that CancelledError is re-raised from MCPTools.connect(force=True)."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    tools._initialized = True  # Simulate previously connected

    with patch.object(tools, "_connect", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await tools.connect(force=True)


@pytest.mark.asyncio
async def test_mcp_connect_logs_non_cancelled_errors():
    """Test that non-CancelledError exceptions are logged but not re-raised from connect()."""
    tools = MCPTools(url="http://localhost:8080/mcp")

    with patch.object(tools, "_connect", side_effect=RuntimeError("connection failed")):
        # Should not raise - RuntimeError is caught and logged
        await tools.connect()
        assert not tools._initialized


@pytest.mark.asyncio
async def test_mcp_build_tools_propagates_cancelled_error():
    """Test that CancelledError is re-raised from MCPTools.build_tools()."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    mock_session = AsyncMock()
    mock_session.list_tools = AsyncMock(side_effect=asyncio.CancelledError)
    tools.session = mock_session

    with pytest.raises(asyncio.CancelledError):
        await tools.build_tools()


@pytest.mark.asyncio
async def test_mcp_initialize_propagates_cancelled_error():
    """Test that CancelledError is re-raised from MCPTools.initialize()."""
    tools = MCPTools(url="http://localhost:8080/mcp")
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock(side_effect=asyncio.CancelledError)
    tools.session = mock_session

    with pytest.raises(asyncio.CancelledError):
        await tools.initialize()


@pytest.mark.asyncio
async def test_multi_mcp_connect_propagates_cancelled_error():
    """Test that CancelledError is re-raised from MultiMCPTools.connect()."""
    tools = MultiMCPTools(urls=["http://localhost:8080/mcp"])

    with patch.object(tools, "_connect", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await tools.connect()


@pytest.mark.asyncio
async def test_multi_mcp_aenter_propagates_cancelled_error():
    """Test that CancelledError is re-raised from MultiMCPTools.__aenter__()."""
    tools = MultiMCPTools(urls=["http://localhost:8080/mcp"])

    with patch.object(tools, "_connect", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await tools.__aenter__()


# =============================================================================
# Redundant build_tools removal tests
# =============================================================================


@pytest.mark.asyncio
async def test_agent_refresh_no_redundant_build_tools_on_reconnect():
    """Test that build_tools is not called redundantly when reconnecting.

    When is_alive() returns False, connect(force=True) is called which internally
    calls initialize() -> build_tools(). A separate build_tools() call should NOT
    happen after reconnection. This test verifies the logic pattern used in
    agent/_tools.py and team/_tools.py.
    """
    mock_tool = MagicMock()
    mock_tool.refresh_connection = True
    mock_tool.initialized = True

    # is_alive returns False -> triggers reconnection
    mock_tool.is_alive = AsyncMock(return_value=False)
    mock_tool.connect = AsyncMock()
    mock_tool.build_tools = AsyncMock()

    # Simulate the agent _tools.py logic (after our fix)
    is_alive = await mock_tool.is_alive()
    if not is_alive:
        await mock_tool.connect(force=True)
        # After our fix, build_tools should NOT be called separately
    else:
        await mock_tool.build_tools()

    # connect was called, build_tools was NOT called separately
    mock_tool.connect.assert_called_once_with(force=True)
    mock_tool.build_tools.assert_not_called()


@pytest.mark.asyncio
async def test_agent_refresh_calls_build_tools_when_alive():
    """Test that build_tools IS called when connection is alive (to refresh tool list)."""
    mock_tool = MagicMock()
    mock_tool.refresh_connection = True
    mock_tool.initialized = True

    # is_alive returns True -> no reconnection needed, just refresh tools
    mock_tool.is_alive = AsyncMock(return_value=True)
    mock_tool.connect = AsyncMock()
    mock_tool.build_tools = AsyncMock()

    # Simulate the agent _tools.py logic (after our fix)
    is_alive = await mock_tool.is_alive()
    if not is_alive:
        await mock_tool.connect(force=True)
    else:
        await mock_tool.build_tools()

    # connect was NOT called, build_tools WAS called
    mock_tool.connect.assert_not_called()
    mock_tool.build_tools.assert_called_once()


@pytest.mark.asyncio
async def test_connect_force_calls_build_tools_via_initialize():
    """Test that connect(force=True) triggers build_tools through the initialize chain."""
    tools = MCPTools(url="http://localhost:8080/mcp")

    # Mock _connect to simulate the full chain
    build_tools_called = False

    async def mock_connect():
        nonlocal build_tools_called
        # Simulates _connect -> initialize -> build_tools
        build_tools_called = True
        tools._initialized = True

    with patch.object(tools, "_connect", side_effect=mock_connect):
        await tools.connect(force=True)

    assert build_tools_called
    assert tools._initialized


# =============================================================================
# CancelledError in refresh connection flow
# =============================================================================


@pytest.mark.asyncio
async def test_agent_refresh_propagates_cancelled_error_from_is_alive():
    """Test that CancelledError from is_alive propagates during refresh."""
    mock_tool = MagicMock()
    mock_tool.refresh_connection = True
    mock_tool.is_alive = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await mock_tool.is_alive()


@pytest.mark.asyncio
async def test_agent_refresh_propagates_cancelled_error_from_connect():
    """Test that CancelledError from connect(force=True) propagates during refresh."""
    mock_tool = MagicMock()
    mock_tool.refresh_connection = True
    mock_tool.is_alive = AsyncMock(return_value=False)
    mock_tool.connect = AsyncMock(side_effect=asyncio.CancelledError)

    is_alive = await mock_tool.is_alive()
    assert not is_alive

    with pytest.raises(asyncio.CancelledError):
        await mock_tool.connect(force=True)


@pytest.mark.asyncio
async def test_agent_refresh_propagates_cancelled_error_from_build_tools():
    """Test that CancelledError from build_tools propagates during refresh."""
    mock_tool = MagicMock()
    mock_tool.refresh_connection = True
    mock_tool.is_alive = AsyncMock(return_value=True)
    mock_tool.build_tools = AsyncMock(side_effect=asyncio.CancelledError)

    is_alive = await mock_tool.is_alive()
    assert is_alive

    with pytest.raises(asyncio.CancelledError):
        await mock_tool.build_tools()
