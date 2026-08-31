"""Declarative marker for publishing a component (Agent/Team/Workflow) as a tool."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from agno.tools.annotations import validate_tool_annotations


@dataclass(frozen=True)
class ComponentTool:
    """Publish an Agent, Team, or Workflow as a tool under its own model-facing name,
    description, title, and behaviour annotations.

    Built via ``component.as_tool(name=..., description=...)`` and consumed by surfaces
    that turn components into tools -- today the AgentOS MCP server
    (``MCPConfig(tools=[...])``). Every override is optional: an omitted ``name`` falls
    back to the component id, an omitted ``description`` to the component's own, an
    omitted ``title`` to the component name (never fetched from a remote just for a
    title), and omitted ``annotations`` to the surface's defaults.

    This is a MARKER, not a callable: binding the component into a plain function here
    would bypass the consuming surface's machinery (for MCP: scope checks, session
    minting, ownership gates, the HITL pause contract, progress reporting). The
    consumer resolves the component and builds the tool itself.

    The tool ``name`` is model-facing UX; the component id remains the handle for
    continue_run/get_sessions and the per-resource scope segment (``agents:<id>:run``).

    ``title`` is the human-facing display name a client shows in place of the tool name;
    ``annotations`` are the MCP behaviour hints (``readOnlyHint`` and friends) merged
    over the publishing surface's defaults, where a ``None`` value drops a default.
    """

    component: Any
    name: Optional[str] = None
    description: Optional[str] = None
    title: Optional[str] = None
    annotations: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        # Validate where the developer typed it: an unknown annotation key reaches a
        # reviewing client as "no annotation at all", which is a listing rejection.
        # Store the validated COPY -- the freeze is shallow, so holding the caller's own
        # dict would let a later edit to it put an unchecked key on a validated marker.
        validated = validate_tool_annotations(self.annotations, "as_tool(annotations=...)")
        object.__setattr__(self, "annotations", validated)


def raise_if_component_tool(tool: Any, owner: str, delegate_hint: str) -> None:
    """Reject a ``ComponentTool`` marker passed where callable tools belong.

    ``Agent(tools=[...])`` / ``Team(tools=[...])`` chains classify entries by shape
    and silently skip what they do not recognize -- a marker would register nothing.
    No repr of the marker in the message: it embeds the component, whose repr can
    carry a model api_key.
    """
    if not isinstance(tool, ComponentTool):
        return
    label = tool.name or getattr(tool.component, "id", None)
    raise ValueError(
        f"{owner}(tools=[...]) got the as_tool() marker for {label!r}: it publishes a component "
        f"on the AgentOS MCP server -- pass it in MCPConfig(tools=[...]) instead. {delegate_hint}"
    )
