"""Router for MCP interface providing Model Context Protocol endpoints.

This module is kept for backwards compatibility.
The actual implementation has moved to agno.os.mcp.server
"""

# Re-export for backwards compatibility
from agno.os.mcp.server import get_mcp_server

__all__ = ["get_mcp_server"]
