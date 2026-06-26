"""Upstream ``agno.team.Team`` with banavo-compatible parameter aliases.

Use this module while migrating off the forked ``agno.banavo.team.team.Team``.
Once migration completes, banavo code should import ``agno.team.Team`` directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, List, Optional, Union

import agno.banavo.message_persistence  # noqa: F401
from agno.agent import Agent as UpstreamAgent
from agno.team import Team as _UpstreamTeam

# Banavo members built on upstream Agent during migration
Agent = UpstreamAgent

# kwargs accepted by forked Team but not upstream — dropped with optional warning in debug
_BANAVO_ONLY_INIT_KEYS = frozenset(
    {
        "disable_built_in_transfer_tools",
        "max_interactions_to_share",
        "monitoring",
        "include_session_state_in_response",
        "team_session_state",
        "memory",
        "storage",
        "custom_transfer_system_prompt",
        "expose_members_to_parent",
        "success_criteria",
        "add_state_in_messages",
        "session_name",
        "enable_agentic_context",
        "read_team_history",
        "add_memory_references",
        "add_session_summary_references",
        "extra_data",
        "telemetry",
        "parser_model_prompt",
        "response_model",
        "add_references",
        "retriever",
        "enable_agentic_knowledge_filters",
        "add_member_tools_to_system_message",
        "add_datetime_to_instructions",
        "add_location_to_instructions",
        "add_context",
        "context",
        "tool_hooks",
        "show_tool_calls",
        "enable_agentic_memory",
        "enable_user_memories",
        "num_of_interactions_from_history",
        "enable_team_history",
        "max_tokens_from_history",
        "reasoning_agent",
        "reasoning_min_steps",
        "reasoning_max_steps",
        "stream_member_events",
        "show_members_responses",
    }
)

_INIT_ALIASES = {
    "team_id": "id",
    "storage": "db",
    "add_history_to_messages": "add_history_to_context",
    "enable_team_history": "add_team_history_to_members",
    "num_history_runs": "num_history_runs",  # same name, kept for clarity
    "stream_intermediate_steps": "stream_events",
}


def _map_init_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in _BANAVO_ONLY_INIT_KEYS:
            if key == "team_session_state":
                mapped.setdefault("session_state", value)
            continue
        target = _INIT_ALIASES.get(key, key)
        if target not in mapped:
            mapped[target] = value
    return mapped


class Team(_UpstreamTeam):
    """Upstream Team with banavo V1 init/arun keyword compatibility."""

    def __init__(self, members: List[Union[Agent, "Team"]], **kwargs: Any) -> None:
        if "team_id" in kwargs and "id" not in kwargs:
            kwargs["id"] = kwargs.pop("team_id")
        if "storage" in kwargs and "db" not in kwargs:
            kwargs["db"] = kwargs.pop("storage")
        kwargs = _map_init_kwargs(kwargs)
        super().__init__(members=members, **kwargs)

    @property
    def team_session_state(self) -> Optional[dict[str, Any]]:
        return self.session_state

    @team_session_state.setter
    def team_session_state(self, value: Optional[dict[str, Any]]) -> None:
        self.session_state = value

    @property
    def team_id(self) -> Optional[str]:
        return self.id

    @team_id.setter
    def team_id(self, value: Optional[str]) -> None:
        self.id = value

    async def arun(  # type: ignore[override]
        self,
        message: Any = None,
        *,
        input: Any = None,
        manage_user_messages: bool = False,
        user_message: Optional[str] = None,
        stream_intermediate_steps: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> Any:
        """Banavo-compatible ``arun`` — maps ``message`` → ``input`` and stream kw aliases."""
        run_input = input if input is not None else message
        if run_input is None:
            raise ValueError("message or input is required")

        if stream_intermediate_steps is not None and stream_events is None:
            stream_events = stream_intermediate_steps

        if manage_user_messages and user_message:
            state = self.session_state or {}
            state.setdefault("message_history", []).append(user_message)
            self.session_state = state

        kwargs.pop("manage_user_messages", None)
        kwargs.pop("user_message", None)
        kwargs.pop("message", None)

        result = super().arun(
            run_input,
            stream=stream,
            stream_events=stream_events,
            **kwargs,
        )

        if stream:
            return result

        return await result


class TeamMemory:
    """Stub for forked TeamMemory references during migration."""

    create_user_memories: bool = False
    create_session_summary: bool = False
