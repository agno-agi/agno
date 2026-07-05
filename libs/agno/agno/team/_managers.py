"""Background task orchestration for memory and learning."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import (
    TYPE_CHECKING,
    Optional,
)

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.team.team import Team

from typing import List

from agno.db.base import UserMemory
from agno.run.messages import RunMessages
from agno.session import TeamSession
from agno.utils.log import log_debug, log_warning

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def _make_memories(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
) -> Optional[RunMetrics]:
    from agno.metrics import RunMetrics

    collector = RunMetrics()
    user_message_str = run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
    if (
        user_message_str is not None
        and user_message_str.strip() != ""
        and team.memory_manager is not None
        and team.update_memory_on_run
    ):
        log_debug("Managing user memories")
        team.memory_manager.create_user_memories(
            message=user_message_str,
            user_id=user_id,
            team_id=team.id,
            run_metrics=collector,
        )
    return collector


async def _amake_memories(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
) -> Optional[RunMetrics]:
    from agno.metrics import RunMetrics

    collector = RunMetrics()
    user_message_str = run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
    if (
        user_message_str is not None
        and user_message_str.strip() != ""
        and team.memory_manager is not None
        and team.update_memory_on_run
    ):
        log_debug("Managing user memories")
        await team.memory_manager.acreate_user_memories(
            message=user_message_str,
            user_id=user_id,
            team_id=team.id,
            run_metrics=collector,
        )
    return collector


async def _astart_memory_task(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_task: Optional[asyncio.Task],
) -> Optional[asyncio.Task]:
    """Cancel any existing memory task and start a new one if conditions are met.

    Args:
        run_messages: The run messages containing the user message.
        user_id: The user ID for memory creation.
        existing_task: An existing memory task to cancel before starting a new one.

    Returns:
        A new memory task if conditions are met, None otherwise.
    """
    # Cancel any existing task from a previous retry attempt
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            pass

    # Create new task if conditions are met
    if (
        run_messages.user_message is not None
        and team.memory_manager is not None
        and team.update_memory_on_run
        and not team.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background task.")
        return asyncio.create_task(_amake_memories(team, run_messages=run_messages, user_id=user_id))

    return None


def _start_memory_future(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_future: Optional[Future],
) -> Optional[Future]:
    """Cancel any existing memory future and start a new one if conditions are met.

    Args:
        run_messages: The run messages containing the user message.
        user_id: The user ID for memory creation.
        existing_future: An existing memory future to cancel before starting a new one.

    Returns:
        A new memory future if conditions are met, None otherwise.
    """
    # Cancel any existing task from a previous retry attempt
    if existing_future is not None and not existing_future.done():
        existing_future.cancel()
        try:
            existing_future.result()
        except Exception:
            pass

    # Create new future if conditions are met
    if (
        run_messages.user_message is not None
        and team.memory_manager is not None
        and team.update_memory_on_run
        and not team.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background task.")
        return asyncio.run_coroutine_threadsafe(_amake_memories(team, run_messages=run_messages, user_id=user_id), asyncio.get_event_loop()).task

    return None


async def _create_session_summary(
    agent_session: TeamSession,
    run_metrics: RunMetrics,
) -> None:
    await agent_session.upsert_run(run_metrics)
    await agent_session.session_summary_manager.acreate_session_summary(
        session=agent_session,
        run_metrics=run_metrics,
    )


async def _start_session_summary_task(
    agent_session: TeamSession,
    run_metrics: RunMetrics,
    existing_task: Optional[asyncio.Task],
) -> Optional[asyncio.Task]:
    """Cancel any existing session summary task and start a new one if conditions are met.

    Args:
        agent_session: The agent session.
        run_metrics: The run metrics.
        existing_task: An existing session summary task to cancel before starting a new one.

    Returns:
        A new session summary task if conditions are met, None otherwise.
    """
    # Cancel any existing task from a previous retry attempt
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            pass

    # Create new task if conditions are met
    if agent_session.session_summary_manager is not None and agent_session.enable_session_summaries:
        log_debug("Starting session summary creation in background task.")
        return asyncio.create_task(_create_session_summary(agent_session, run_metrics))

    return None