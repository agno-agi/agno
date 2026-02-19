"""Tests for SSE transport concurrent MCP method call handling.

Verifies that:
1. The blocking send_ping() before each tool call has been removed
2. A concurrency semaphore is used to bound parallel calls
3. Concurrent tool calls actually run in parallel (not serialized)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools


@pytest.mark.asyncio
async def test_call_tool_no_ping_before_call():
    """Verify that send_ping is NOT called before each tool call.

    The old implementation called send_ping() before every call_tool(),
    which serialized concurrent requests through the SSE transport.
    """
    from agno.utils.mcp import get_entrypoint_for_tool

    mock_session = AsyncMock()
    mock_tool = MagicMock()
    mock_tool.name = "test_tool"

    # Set up call_tool to return a valid result
    mock_result = MagicMock()
    mock_result.isError = False
    mock_text = MagicMock()
    mock_text.text = "result"
    # Use the actual TextContent type name for isinstance checks
    type(mock_text).__name__ = "TextContent"
    mock_result.content = [mock_text]
    mock_session.call_tool.return_value = mock_result

    # Patch TextContent isinstance check
    with patch("agno.utils.mcp.TextContent") as mock_tc:
        mock_tc.return_value = mock_text
        # Make isinstance check work
        mock_text.__class__ = mock_tc

        entrypoint = get_entrypoint_for_tool(
            tool=mock_tool,
            session=mock_session,
            mcp_tools_instance=None,
        )

        await entrypoint()

    # send_ping should NOT have been called
    mock_session.send_ping.assert_not_called()
    # call_tool should have been called
    mock_session.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_tools_has_call_semaphore():
    """MCPTools should have a _call_semaphore attribute for concurrency control."""
    tools = MCPTools(url="http://localhost:8080/sse", transport="sse")
    assert hasattr(tools, "_call_semaphore")
    assert isinstance(tools._call_semaphore, asyncio.Semaphore)


@pytest.mark.asyncio
async def test_multi_mcp_tools_has_call_semaphore():
    """MultiMCPTools should have a _call_semaphore attribute for concurrency control."""
    tools = MultiMCPTools(urls=["http://localhost:8080/sse"], urls_transports=["sse"])
    assert hasattr(tools, "_call_semaphore")
    assert isinstance(tools._call_semaphore, asyncio.Semaphore)


@pytest.mark.asyncio
async def test_concurrent_calls_not_fully_serialized():
    """Concurrent MCP tool calls should execute in parallel, not be serialized.

    We simulate 5 concurrent tool calls that each take 0.1s.
    If they were serialized, total time would be >= 0.5s.
    With concurrency, total time should be close to 0.1s.
    """
    from agno.utils.mcp import get_entrypoint_for_tool

    call_times = []

    async def mock_call_tool(name, args):
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.05)
        end = asyncio.get_event_loop().time()
        call_times.append((start, end))
        result = MagicMock()
        result.isError = False
        mock_text = MagicMock()
        mock_text.text = "ok"
        result.content = [mock_text]
        return result

    mock_session = AsyncMock()
    mock_session.call_tool = mock_call_tool

    mock_tool = MagicMock()
    mock_tool.name = "slow_tool"

    # Create entrypoint WITHOUT mcp_tools_instance so no semaphore is used
    # (tests pure concurrency without semaphore throttling)
    with patch("agno.utils.mcp.isinstance", return_value=True):
        entrypoint = get_entrypoint_for_tool(
            tool=mock_tool,
            session=mock_session,
            mcp_tools_instance=None,
        )

    num_calls = 5
    start_time = asyncio.get_event_loop().time()
    tasks = [asyncio.create_task(entrypoint()) for _ in range(num_calls)]
    await asyncio.gather(*tasks)
    total_time = asyncio.get_event_loop().time() - start_time

    assert len(call_times) == num_calls
    # If calls ran concurrently, total time should be much less than
    # num_calls * 0.05 = 0.25s. Allow generous margin for CI.
    assert total_time < 0.2, f"Concurrent calls took {total_time:.3f}s, expected < 0.2s (calls may be serialized)"


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """The semaphore should limit but not fully serialize concurrent calls.

    With a semaphore of size 2 and 4 calls of 0.05s each:
    - Fully parallel: ~0.05s
    - Semaphore(2): ~0.10s (2 batches of 2)
    - Fully serial: ~0.20s
    """
    from agno.utils.mcp import get_entrypoint_for_tool

    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def mock_call_tool(name, args):
        nonlocal active_count, max_active
        async with lock:
            active_count += 1
            if active_count > max_active:
                max_active = active_count
        await asyncio.sleep(0.05)
        async with lock:
            active_count -= 1
        result = MagicMock()
        result.isError = False
        mock_text = MagicMock()
        mock_text.text = "ok"
        result.content = [mock_text]
        return result

    mock_session = AsyncMock()
    mock_session.call_tool = mock_call_tool

    mock_tool = MagicMock()
    mock_tool.name = "throttled_tool"

    # Create MCPTools instance with a small semaphore for testing
    mcp_tools = MCPTools(url="http://localhost:8080/sse", transport="sse")
    mcp_tools._call_semaphore = asyncio.Semaphore(2)
    mcp_tools.session = mock_session

    entrypoint = get_entrypoint_for_tool(
        tool=mock_tool,
        session=mock_session,
        mcp_tools_instance=mcp_tools,
    )

    num_calls = 4
    tasks = [asyncio.create_task(entrypoint()) for _ in range(num_calls)]
    await asyncio.gather(*tasks)

    # With semaphore(2), max concurrency should be <= 2
    assert max_active <= 2, f"Max active calls was {max_active}, expected <= 2"
    # But calls should still be concurrent (not fully serial)
    assert max_active >= 2, f"Max active calls was {max_active}, expected >= 2"


@pytest.mark.asyncio
async def test_semaphore_default_value():
    """Default semaphore should allow reasonable concurrency (10)."""
    tools = MCPTools(url="http://localhost:8080/sse", transport="sse")
    # The semaphore's internal value starts at 10
    assert tools._call_semaphore._value == 10


@pytest.mark.asyncio
async def test_call_tool_works_without_mcp_tools_instance():
    """When no mcp_tools_instance is provided, call_tool should work
    without semaphore and without ping.
    """
    from mcp.types import TextContent

    from agno.utils.mcp import get_entrypoint_for_tool

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.isError = False
    mock_result.content = [TextContent(type="text", text="hello")]
    mock_session.call_tool.return_value = mock_result

    mock_tool = MagicMock()
    mock_tool.name = "basic_tool"

    entrypoint = get_entrypoint_for_tool(
        tool=mock_tool,
        session=mock_session,
        mcp_tools_instance=None,
    )

    result = await entrypoint()

    mock_session.send_ping.assert_not_called()
    mock_session.call_tool.assert_called_once_with("basic_tool", {})
    assert result.content == "hello"
