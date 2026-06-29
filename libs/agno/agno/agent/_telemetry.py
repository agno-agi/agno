"""Telemetry logging helpers for Agent."""

from __future__ import annotations

import asyncio
from queue import Full, Queue
from threading import Lock, Thread
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.utils.log import log_debug

_BACKGROUND_AGENT_TELEMETRY_TASKS: Set[asyncio.Task] = set()
_AGENT_TELEMETRY_QUEUE = Queue(maxsize=128)
_AGENT_TELEMETRY_WORKER_LOCK = Lock()
_AGENT_TELEMETRY_WORKER_STARTED = False


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


def _create_agent_run_background(run: Any) -> None:
    from agno.api.agent import create_agent_run

    try:
        create_agent_run(run=run)
    except Exception as e:
        log_debug(f"Could not create Agent run telemetry event: {e}")


def _agent_telemetry_worker() -> None:
    while True:
        run = _AGENT_TELEMETRY_QUEUE.get()
        try:
            _create_agent_run_background(run)
        finally:
            _AGENT_TELEMETRY_QUEUE.task_done()


def _ensure_agent_telemetry_worker() -> None:
    global _AGENT_TELEMETRY_WORKER_STARTED

    if _AGENT_TELEMETRY_WORKER_STARTED:
        return

    with _AGENT_TELEMETRY_WORKER_LOCK:
        if _AGENT_TELEMETRY_WORKER_STARTED:
            return
        Thread(target=_agent_telemetry_worker, daemon=True, name="agno-agent-telemetry").start()
        _AGENT_TELEMETRY_WORKER_STARTED = True


def _enqueue_agent_telemetry_run(run: Any) -> None:
    _ensure_agent_telemetry_worker()
    try:
        _AGENT_TELEMETRY_QUEUE.put_nowait(run)
    except Full:
        log_debug("Could not create Agent run telemetry event: background queue is full")


def _handle_agent_telemetry_task_done(task: asyncio.Task) -> None:
    _BACKGROUND_AGENT_TELEMETRY_TASKS.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log_debug(f"Could not create Agent run telemetry event: {e}")


def log_agent_telemetry(agent: Agent, session_id: str, run_id: Optional[str] = None) -> None:
    """Send a telemetry event to the API for a created Agent run."""
    from agno.agent import _init

    _init.set_telemetry(agent)
    if not agent.telemetry:
        return

    from agno.api.agent import AgentRunCreate

    try:
        run = AgentRunCreate(
            session_id=session_id,
            run_id=run_id,
            data=get_telemetry_data(agent),
        )
        _enqueue_agent_telemetry_run(run)
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
        run = AgentRunCreate(
            session_id=session_id,
            run_id=run_id,
            data=get_telemetry_data(agent),
        )
        task = asyncio.create_task(acreate_agent_run(run=run))
        _BACKGROUND_AGENT_TELEMETRY_TASKS.add(task)
        task.add_done_callback(_handle_agent_telemetry_task_done)
    except Exception as e:
        log_debug(f"Could not create Agent run telemetry event: {e}")
