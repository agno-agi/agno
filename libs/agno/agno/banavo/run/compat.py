"""V1/V2 run event compatibility for banavo streaming and nested tool generators.

Forked ``agno.banavo`` Agent/Team emit V1-named content events (``RunResponseContent``,
``TeamRunResponseContent``). Upstream agno 2.6.x emits V2 names (``RunContent``,
``TeamRunContent``). Helpers here accept both until Agent/Team migrate to upstream.
"""

from __future__ import annotations

from typing import Any

from agno.run.agent import BaseAgentRunEvent
from agno.run.agent import RunContentEvent as AgentRunContentEventV2
from agno.run.base import BaseRunOutputEvent
from agno.run.team import BaseTeamRunEvent
from agno.run.team import RunContentEvent as TeamRunContentEventV2

from agno.banavo.run.response import BaseAgentRunResponseEvent
from agno.banavo.run.response import RunResponseContentEvent as AgentRunResponseContentEventV1
from agno.banavo.run.team import BaseTeamRunResponseEvent
from agno.banavo.run.team import RunResponseContentEvent as TeamRunResponseContentEventV1

# Legacy V1 content event names (forked Agent/Team)
V1_AGENT_CONTENT_EVENTS = frozenset({"RunResponseContent"})
V1_TEAM_CONTENT_EVENTS = frozenset({"TeamRunResponseContent"})

# Upstream V2 content event names
V2_AGENT_CONTENT_EVENTS = frozenset({"RunContent", "RunIntermediateContent"})
V2_TEAM_CONTENT_EVENTS = frozenset({"TeamRunContent", "TeamRunIntermediateContent"})

ALL_CONTENT_EVENT_NAMES = (
    V1_AGENT_CONTENT_EVENTS | V1_TEAM_CONTENT_EVENTS | V2_AGENT_CONTENT_EVENTS | V2_TEAM_CONTENT_EVENTS
)

_CONTENT_EVENT_TYPES = (
    AgentRunResponseContentEventV1,
    TeamRunResponseContentEventV1,
    AgentRunContentEventV2,
    TeamRunContentEventV2,
)

_RUN_EVENT_BASE_TYPES = (
    BaseRunOutputEvent,
    BaseAgentRunResponseEvent,
    BaseTeamRunResponseEvent,
    BaseAgentRunEvent,
    BaseTeamRunEvent,
)


def get_event_name(event: Any) -> str | None:
    name = getattr(event, "event", None)
    return name if isinstance(name, str) else None


def is_content_event(event: Any) -> bool:
    """True for V1 or V2 streaming content deltas (suppress in nested tool bubbles)."""
    if isinstance(event, _CONTENT_EVENT_TYPES):
        return True
    name = get_event_name(event)
    return bool(name and name in ALL_CONTENT_EVENT_NAMES)


def is_run_lifecycle_event(event: Any) -> bool:
    """True for agno run event dataclasses (V1 banavo or V2 upstream)."""
    return isinstance(event, _RUN_EVENT_BASE_TYPES)


def should_forward_nested_event(event: Any) -> bool:
    """Forward lifecycle/tool stream events but suppress content deltas."""
    return is_run_lifecycle_event(event) and not is_content_event(event)


def should_bubble_event(event: Any) -> bool:
    """Alias for :func:`should_forward_nested_event`."""
    return should_forward_nested_event(event)


def team_run_output_to_banavo_response(run_output: Any, team: Any = None) -> Any:
    """Map upstream ``TeamRunOutput`` to forked ``TeamRunResponse`` for transfer tools."""
    from agno.banavo.run.team import TeamRunResponse

    team_name = getattr(run_output, "team_name", None) or getattr(team, "name", None)
    team_id = getattr(run_output, "team_id", None) or getattr(team, "id", None)
    session_id = getattr(run_output, "session_id", None)

    return TeamRunResponse(
        run_id=getattr(run_output, "run_id", None),
        team_id=team_id,
        team_name=team_name,
        session_id=session_id,
        team_session_id=session_id,
        content=getattr(run_output, "content", None),
        tools=getattr(run_output, "tools", None),
        messages=getattr(run_output, "messages", None),
        metrics=getattr(run_output, "metrics", None),
    )
