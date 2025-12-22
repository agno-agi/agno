"""MCP Tools modules - each module registers tools for a specific domain. These should map 1:1 with the routes in the OS."""

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

__all__ = [
    "register_agent_tools",
    "register_core_tools",
    "register_eval_tools",
    "register_knowledge_tools",
    "register_memory_tools",
    "register_metrics_tools",
    "register_session_tools",
    "register_team_tools",
    "register_traces_tools",
    "register_workflow_tools",
]
