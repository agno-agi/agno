"""MCP Server setup for AgentOS - combines all tool modules."""

import logging
from typing import TYPE_CHECKING, Optional

from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from agno.os.mcp.tools.agents import register_agent_tools
from agno.os.mcp.tools.core import register_core_tools
from agno.os.mcp.tools.evals import register_eval_tools
from agno.os.mcp.tools.knowledge import register_knowledge_tools
from agno.os.mcp.tools.memory import register_memory_tools
from agno.os.mcp.tools.metrics import register_metrics_tools
from agno.os.mcp.tools.sessions import register_session_tools
from agno.os.mcp.tools.teams import register_team_tools
from agno.os.mcp.tools.traces import register_traces_tools
from agno.os.mcp.tools.workflows import register_workflow_tools
from agno.os.settings import AgnoAPISettings

if TYPE_CHECKING:
    from agno.os.app import AgentOS

logger = logging.getLogger(__name__)


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for MCP server endpoints."""

    def __init__(self, app, settings: Optional[AgnoAPISettings] = None):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        # If no security key is set, skip authentication entirely
        if not self.settings or not self.settings.os_security_key:
            return await call_next(request)

        # Get the Authorization header
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header required"},
            )

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authorization header format. Expected: Bearer <token>"},
            )

        token = parts[1]

        # Verify the token
        if token != self.settings.os_security_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication token"},
            )

        return await call_next(request)


def get_mcp_server(os: "AgentOS", settings: Optional[AgnoAPISettings] = None) -> StarletteWithLifespan:
    """Create and configure the MCP server with all registered tools.

    Args:
        os: The AgentOS instance to expose via MCP
        settings: Optional API settings for authentication configuration

    Returns:
        A Starlette app configured as an MCP server
    """
    # Create the MCP server
    mcp = FastMCP(os.name or "AgentOS")

    # Register all tool modules
    register_core_tools(mcp, os)
    register_agent_tools(mcp, os)
    register_team_tools(mcp, os)
    register_workflow_tools(mcp, os)
    register_session_tools(mcp, os)
    register_memory_tools(mcp, os)
    register_knowledge_tools(mcp, os)
    register_eval_tools(mcp, os)
    register_metrics_tools(mcp, os)
    register_traces_tools(mcp, os)

    # Create the HTTP app
    mcp_app = mcp.http_app(path="/mcp")

    # Add authentication middleware if settings are provided
    if settings:
        mcp_app.add_middleware(MCPAuthMiddleware, settings=settings)

    return mcp_app
