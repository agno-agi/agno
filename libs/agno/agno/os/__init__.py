from typing import TYPE_CHECKING, Any

from agno.os.app import AgentOS
from agno.os.config import MCP_BUILTIN_TAGS, MCPBuiltinTag, MCPServerConfig

if TYPE_CHECKING:
    from agno.os.mcp_auth_builtin import AgentOSBuiltinAuth

__all__ = ["AgentOS", "MCPServerConfig", "MCPBuiltinTag", "MCP_BUILTIN_TAGS"]


def __getattr__(name: str) -> Any:
    # Lazy so importing agno.os does not require the `mcp` extra (fastmcp); the built-in
    # MCP OAuth server is only pulled in when a deployment actually uses it.
    if name == "AgentOSBuiltinAuth":
        from agno.os.mcp_auth_builtin import AgentOSBuiltinAuth

        return AgentOSBuiltinAuth
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
