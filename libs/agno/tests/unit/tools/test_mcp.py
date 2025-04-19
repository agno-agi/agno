import pytest
from unittest.mock import patch

from agno.tools.mcp import MCPTools


@pytest.mark.asyncio
async def test_sse_transport_without_url():
    """Test that ValueError is raised when transport is SSE but URL is not provided."""
    with pytest.raises(ValueError, match="URL must be provided when using SSE transport"):
        async with MCPTools(transport="sse") as mcp_tools:
            pass


@pytest.mark.asyncio
async def test_stdio_transport_without_server_params():
    """Test that ValueError is raised when transport is stdio but server_params is None."""
    with pytest.raises(ValueError, match="server_params must be provided when using stdio transport"):
        async with MCPTools(transport="stdio") as mcp_tools:
            pass


def test_empty_command_string():
    """Test that ValueError is raised when command string is empty."""
    with pytest.raises(ValueError, match="Empty command string"):
        # Mock shlex.split to return an empty list
        with patch('shlex.split', return_value=[]):
            MCPTools(command="")
