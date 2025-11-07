"""MCP Client for connecting to Model Context Protocol servers."""

from contextlib import AsyncExitStack
from typing import List, Optional

from agno.tools.mcp import MCPTools
from agno.utils.log import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server."""

    id: str
    command: str
    args: Optional[List[str]] = None


class MCPClient:
    """Client for connecting to MCP servers."""

    def __init__(self):
        # Initialize session and client objects
        self.session = None
        self.exit_stack = AsyncExitStack()
        self.tools = []
        self.server_id = None

    async def connect_to_server(self, server_config: MCPServerConfig) -> MCPTools:
        """Connect to an MCP server using the provided configuration.

        Args:
            server_config: Configuration for the MCP server

        Returns:
            MCPTools instance for interacting with the server
        """
        self.server_id = server_config.id

        server_params = StdioServerParameters(
            command=server_config.command,
            args=server_config.args,
        )
        logger.info(f"Connecting to server {self.server_id}")

        # Create client session
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        # Initialize the session
        await self.session.initialize()

        # Create MCPTools for this server
        mcp_tools = MCPTools(session=self.session)
        await mcp_tools.initialize()
        logger.info(f"Connected to server {self.server_id}")

        return mcp_tools

    async def cleanup(self):
        """Clean up resources."""
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            logger.warning(f"Error during MCP client cleanup: {e}")
