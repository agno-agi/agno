from unittest.mock import patch

import pytest

from agno.tools.mcp import MCPTools, MultiMCPTools, SSEClientParams


@pytest.mark.asyncio
async def test_sse_transport_without_url():
    """Test that ValueError is raised when transport is SSE but URL is not provided."""
    with pytest.raises(ValueError, match="The 'url' parameter must be provided"):
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
    with pytest.raises(ValueError, match="Either server_params_list, commands, or sse_endpoints must be provided"):
        async with MultiMCPTools():
            pass


@pytest.mark.asyncio
async def test_multimcp_sse_endpoint_without_url():
    """Test that ValueError is raised when an SSE endpoint doesn't have a URL."""
    sse_params = SSEClientParams()
    with pytest.raises(ValueError, match="URL must be provided as a string for SSE endpoint"):
        async with MultiMCPTools(sse_endpoints=[{"params": sse_params}]):
            pass


def test_multimcp_empty_command_string():
    """Test that ValueError is raised when a command string is empty."""
    with pytest.raises(ValueError, match="Empty command string"):
        # Mock shlex.split to return an empty list
        with patch("shlex.split", return_value=[]):
            MultiMCPTools(commands=[""])
