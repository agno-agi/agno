"""Background task orchestration for memory."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import (
    TYPE_CHECKING,
    Optional,
)

if TYPE_CHECKING:
    from agno.team.team import Team

from typing import List

from agno.db.base import UserMemory
from agno.run.messages import RunMessages
from agno.utils.log import log_debug

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def _make_memories(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
):
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
        )


async def _amake_memories(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
):
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
        )


async def _astart_memory_task(
    team: Team,
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_task: Optional[asyncio.Task[None]],
) -> Optional[asyncio.Task[None]]:
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
    existing_future: Optional[Future[None]],
) -> Optional[Future[None]]:
    """Cancel any existing memory future and start a new one if conditions are met.

    Args:
        run_messages: The run messages containing the user message.
        user_id: The user ID for memory creation.
        existing_future: An existing memory future to cancel before starting a new one.

    Returns:
        A new memory future if conditions are met, None otherwise.
    """
    # Cancel any existing future from a previous retry attempt
    if existing_future is not None and not existing_future.done():
        existing_future.cancel()

    # Create new future if conditions are met
    if (
        run_messages.user_message is not None
        and team.memory_manager is not None
        and team.update_memory_on_run
        and not team.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background thread.")
        return team.background_executor.submit(_make_memories, team, run_messages=run_messages, user_id=user_id)

    return None


def get_user_memories(team: "Team", user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    from agno.team._init import _set_memory_manager

    if team.memory_manager is None:
        _set_memory_manager(team)

    user_id = user_id if user_id is not None else team.user_id
    if user_id is None:
        user_id = "default"

    return team.memory_manager.get_user_memories(user_id=user_id)  # type: ignore


async def aget_user_memories(team: "Team", user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    from agno.team._init import _set_memory_manager

    if team.memory_manager is None:
        _set_memory_manager(team)

    user_id = user_id if user_id is not None else team.user_id
    if user_id is None:
        user_id = "default"

    return await team.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore
