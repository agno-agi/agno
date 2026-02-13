"""Telemetry logging helpers for Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.utils.log import log_debug


def get_telemetry_data(agent: Agent) -> Dict[str, Any]:
    """Get the telemetry data for the agent."""
    return {
        "agent_id": agent.id,
        "db_type": agent.db.__class__.__name__ if agent.db else None,
        "model_provider": agent.model.provider if agent.model else None,
        "model_name": agent.model.name if agent.model else None,
        "model_id": agent.model.id if agent.model else None,
        "parser_model": agent.parser_model.to_dict() if agent.parser_model else None,
        "output_model": agent.output_model.to_dict() if agent.output_model else None,
        "has_tools": agent.tools is not None,
        "has_memory": agent.update_memory_on_run is True
        or agent.enable_agentic_memory is True
        or agent.memory_manager is not None,
        "has_learnings": agent._learning is not None,
        "has_culture": agent.enable_agentic_culture is True
        or agent.update_cultural_knowledge is True
        or agent.culture_manager is not None,
        "has_reasoning": agent.reasoning is True,
        "has_knowledge": agent.knowledge is not None,
        "has_input_schema": agent.input_schema is not None,
        "has_output_schema": agent.output_schema is not None,
        "has_team": agent.team_id is not None,
    }


def log_agent_telemetry(agent: Agent, session_id: str, run_id: Optional[str] = None) -> None:
    """Send a telemetry event to the API for a created Agent run."""
    from agno.agent import _init

    _init.set_telemetry(agent)
    if not agent.telemetry:
        return

    from agno.api.agent import AgentRunCreate, create_agent_run

    try:
        create_agent_run(
            run=AgentRunCreate(
                session_id=session_id,
                run_id=run_id,
                data=get_telemetry_data(agent),
            ),
        )
    except Exception as e:
        log_debug(f"Could not create Agent run telemetry event: {e}")


async def alog_agent_telemetry(agent: Agent, session_id: str, run_id: Optional[str] = None) -> None:
    """Send a telemetry event to the API for a created Agent async run."""
    from agno.agent import _init

    _init.set_telemetry(agent)
    if not agent.telemetry:
        return

    from agno.api.agent import AgentRunCreate, acreate_agent_run

    try:
        await acreate_agent_run(
            run=AgentRunCreate(
                session_id=session_id,
                run_id=run_id,
                data=get_telemetry_data(agent),
            )
        )
    except Exception as e:
        log_debug(f"Could not create Agent run telemetry event: {e}")
