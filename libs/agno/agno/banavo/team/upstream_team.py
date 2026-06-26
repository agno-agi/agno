"""Upstream ``agno.team.Team`` with banavo-compatible parameter aliases.

Banavo code should import ``Agent`` and ``Team`` from ``agno.banavo.agent`` / ``agno.banavo.team``
(which re-export this module) until call sites migrate to ``agno.agent`` / ``agno.team`` directly.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

import agno.banavo.message_persistence  # noqa: F401
from agno.agent import Agent as UpstreamAgent
from agno.memory.team import TeamMemory as UpstreamTeamMemory
from agno.team import Team as _UpstreamTeam

Agent = UpstreamAgent
TeamMemory = UpstreamTeamMemory

# kwargs accepted by forked Team but not upstream — dropped after explicit handling
_BANAVO_ONLY_INIT_KEYS = frozenset(
    {
        "disable_built_in_transfer_tools",
        "max_interactions_to_share",
        "monitoring",
        "include_session_state_in_response",
        "team_session_state",
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
    "add_history_to_messages": "add_history_to_context",
    "enable_team_history": "add_team_history_to_members",
    "num_history_runs": "num_history_runs",
    "stream_intermediate_steps": "stream_events",
}


def _storage_to_postgres_db(storage: Any) -> Any:
    """Map V1 ``PostgresStorage`` to upstream ``PostgresDb`` when possible."""
    from agno.storage.postgres import PostgresStorage

    if not isinstance(storage, PostgresStorage):
        return storage

    from agno.db.postgres import PostgresDb

    return PostgresDb(
        db_url=storage.db_url,
        session_table=storage.table_name,
    )


def _resolve_db_and_memory(kwargs: dict[str, Any]) -> None:
    """Convert banavo ``storage`` / ``memory`` kwargs to upstream ``db`` / ``memory_manager``."""
    storage = kwargs.pop("storage", None)
    memory = kwargs.pop("memory", None)

    if kwargs.get("db") is not None:
        if memory is not None:
            from agno.banavo.memory.memory import Memory as BanavoMemory

            if isinstance(memory, BanavoMemory) and memory.memory_manager is not None:
                kwargs.setdefault("memory_manager", memory.memory_manager)
        return

    db_url: str | None = None
    session_table = "agent_sessions"
    memory_table = "memories"

    if storage is not None:
        converted = _storage_to_postgres_db(storage)
        if converted is not storage:
            kwargs["db"] = converted
            return
        db_url = getattr(storage, "db_url", None)
        session_table = getattr(storage, "table_name", session_table)

    if memory is not None:
        from agno.banavo.memory.memory import Memory as BanavoMemory

        if isinstance(memory, BanavoMemory):
            if memory.memory_manager is not None:
                kwargs.setdefault("memory_manager", memory.memory_manager)
            mem_db = memory.db
            if mem_db is not None:
                db_url = db_url or getattr(mem_db, "db_url", None)
                memory_table = getattr(mem_db, "table_name", memory_table)

    if db_url and "db" not in kwargs:
        from agno.db.postgres import PostgresDb

        kwargs["db"] = PostgresDb(
            db_url=db_url,
            session_table=session_table,
            memory_table=memory_table,
        )


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
    """Upstream Team with banavo init/arun keyword compatibility."""

    def __init__(self, members: List[Union[Agent, "Team"]], **kwargs: Any) -> None:
        disable_built_in = kwargs.pop("disable_built_in_transfer_tools", False)
        if disable_built_in:
            members = []

        if "team_id" in kwargs and "id" not in kwargs:
            kwargs["id"] = kwargs.pop("team_id")

        _resolve_db_and_memory(kwargs)
        kwargs = _map_init_kwargs(kwargs)
        super().__init__(members=members, **kwargs)
        self.run_response = None

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
