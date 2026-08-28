"""Declarative marker for publishing a component (Agent/Team/Workflow) as a tool."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ComponentTool:
    """Publish an Agent, Team, or Workflow as a tool under its own model-facing name
    and description.

    Built via ``component.as_tool(name=..., description=...)`` and consumed by surfaces
    that turn components into tools -- today the AgentOS MCP server
    (``MCPConfig(tools=[...])``). Both overrides are optional: an omitted ``name`` falls
    back to the component id, an omitted ``description`` to the component's own.

    This is a MARKER, not a callable: binding the component into a plain function here
    would bypass the consuming surface's machinery (for MCP: scope checks, session
    minting, ownership gates, the HITL pause contract, progress reporting). The
    consumer resolves the component and builds the tool itself.

    The tool ``name`` is model-facing UX; the component id remains the handle for
    continue_run/get_sessions and the per-resource scope segment (``agents:<id>:run``).
    """

    component: Any
    name: Optional[str] = None
    description: Optional[str] = None
