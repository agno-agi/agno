from unittest.mock import AsyncMock, patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools


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


def test_empty_command_string():
    """Test that ValueError is raised when command string is empty."""
    with pytest.raises(ValueError, match="Empty command string"):
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
    with pytest.raises(ValueError, match="Empty command string"):
        # Mock shlex.split to return an empty list
        with patch("shlex.split", return_value=[]):
            MultiMCPTools(commands=[""])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mcp_tools,kwargs",
    (
        (MCPTools, {"command": "echo foo", "include_tools": ["foo"]}),
        (MCPTools, {"command": "echo foo", "exclude_tools": ["foo"]}),
    ),
)
async def test_mcp_include_exclude_tools_bad_values(mcp_tools, kwargs):
    """Test that _check_tools_filters raises ValueError during initialize"""
    session_mock = AsyncMock()
    tool_mock = AsyncMock()
    tool_mock.__name__ = "baz"
    tools = AsyncMock()
    tools.tools = [tool_mock]
    session_mock.list_tools.return_value = tools

    # _check_tools_filters should be bypassed during __init__
    tools = mcp_tools(**kwargs)
    with pytest.raises(ValueError, match="not present in the toolkit"):
        tools.session = session_mock
        await tools.initialize()
