"""Background task orchestration for memory, learning, and cultural knowledge."""

from __future__ import annotations

from asyncio import CancelledError, Task, create_task
from concurrent.futures import Future
from typing import (
    TYPE_CHECKING,
    List,
    Optional,
)

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.db.base import UserMemory
from agno.db.schemas.culture import CulturalKnowledge
from agno.models.message import Message
from agno.run.messages import RunMessages
from agno.session import AgentSession
from agno.utils.log import log_debug, log_warning

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def make_memories(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
):
    user_message_str = run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
    if (
        user_message_str is not None
        and user_message_str.strip() != ""
        and agent.memory_manager is not None
        and agent.update_memory_on_run
    ):
        log_debug("Managing user memories")
        agent.memory_manager.create_user_memories(  # type: ignore
            message=user_message_str,
            user_id=user_id,
            agent_id=agent.id,
        )

    if run_messages.extra_messages is not None and len(run_messages.extra_messages) > 0:
        parsed_messages = []
        for _im in run_messages.extra_messages:
            if isinstance(_im, Message):
                parsed_messages.append(_im)
            elif isinstance(_im, dict):
                try:
                    parsed_messages.append(Message(**_im))
                except Exception as e:
                    log_warning(f"Failed to validate message during memory update: {e}")
            else:
                log_warning(f"Unsupported message type: {type(_im)}")
                continue

        # Filter out messages with empty content before passing to memory manager
        non_empty_messages = [
            msg
            for msg in parsed_messages
            if msg.content and (not isinstance(msg.content, str) or msg.content.strip() != "")
        ]
        if len(non_empty_messages) > 0:
            if agent.memory_manager is not None and agent.update_memory_on_run:
                agent.memory_manager.create_user_memories(
                    messages=non_empty_messages, user_id=user_id, agent_id=agent.id
                )  # type: ignore
            else:
                log_warning(
                    "Unable to add messages to memory: memory_manager not configured or update_memory_on_run is disabled"
                )


async def amake_memories(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
):
    user_message_str = run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
    if (
        user_message_str is not None
        and user_message_str.strip() != ""
        and agent.memory_manager is not None
        and agent.update_memory_on_run
    ):
        log_debug("Managing user memories")
        await agent.memory_manager.acreate_user_memories(  # type: ignore
            message=user_message_str,
            user_id=user_id,
            agent_id=agent.id,
        )

    if run_messages.extra_messages is not None and len(run_messages.extra_messages) > 0:
        parsed_messages = []
        for _im in run_messages.extra_messages:
            if isinstance(_im, Message):
                parsed_messages.append(_im)
            elif isinstance(_im, dict):
                try:
                    parsed_messages.append(Message(**_im))
                except Exception as e:
                    log_warning(f"Failed to validate message during memory update: {e}")
            else:
                log_warning(f"Unsupported message type: {type(_im)}")
                continue

        # Filter out messages with empty content before passing to memory manager
        non_empty_messages = [
            msg
            for msg in parsed_messages
            if msg.content and (not isinstance(msg.content, str) or msg.content.strip() != "")
        ]
        if len(non_empty_messages) > 0:
            if agent.memory_manager is not None and agent.update_memory_on_run:
                await agent.memory_manager.acreate_user_memories(  # type: ignore
                    messages=non_empty_messages, user_id=user_id, agent_id=agent.id
                )
            else:
                log_warning(
                    "Unable to add messages to memory: memory_manager not configured or update_memory_on_run is disabled"
                )


async def astart_memory_task(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_task: Optional[Task[None]],
) -> Optional[Task[None]]:
    """Cancel any existing memory task and start a new one if conditions are met.

    Args:
        agent: The Agent instance.
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
        except CancelledError:
            pass

    # Create new task if conditions are met
    if (
        run_messages.user_message is not None
        and agent.memory_manager is not None
        and agent.update_memory_on_run
        and not agent.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background task.")
        return create_task(amake_memories(agent, run_messages=run_messages, user_id=user_id))

    return None


def start_memory_future(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_future: Optional[Future] = None,
) -> Optional[Future]:
    """Cancel any existing memory future and start a new one if conditions are met.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing the user message.
        user_id: The user ID for memory creation.
        existing_future: An existing memory future to cancel before starting a new one.

    Returns:
        A new memory future if conditions are met, None otherwise.
    """
    # Cancel any existing future from a previous retry attempt
    # Note: cancel() only works if the future hasn't started yet
    if existing_future is not None and not existing_future.done():
        existing_future.cancel()

    # Create new future if conditions are met
    if (
        run_messages.user_message is not None
        and agent.memory_manager is not None
        and agent.update_memory_on_run
        and not agent.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background thread.")
        return agent.background_executor.submit(make_memories, agent, run_messages=run_messages, user_id=user_id)

    return None


def get_user_memories(agent: Agent, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        agent: The Agent instance.
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    from agno.agent._init import set_memory_manager

    if agent.memory_manager is None:
        set_memory_manager(agent)

    user_id = user_id if user_id is not None else agent.user_id
    if user_id is None:
        user_id = "default"

    return agent.memory_manager.get_user_memories(user_id=user_id)  # type: ignore


async def aget_user_memories(agent: Agent, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
    """Get the user memories for the given user ID.

    Args:
        agent: The Agent instance.
        user_id: The user ID to get the memories for. If not provided, the current cached user ID is used.
    Returns:
        Optional[List[UserMemory]]: The user memories.
    """
    from agno.agent._init import set_memory_manager

    if agent.memory_manager is None:
        set_memory_manager(agent)

    user_id = user_id if user_id is not None else agent.user_id
    if user_id is None:
        user_id = "default"

    return await agent.memory_manager.aget_user_memories(user_id=user_id)  # type: ignore


# ---------------------------------------------------------------------------
# Cultural knowledge
# ---------------------------------------------------------------------------


def make_cultural_knowledge(
    agent: Agent,
    run_messages: RunMessages,
):
    if run_messages.user_message is not None and agent.culture_manager is not None and agent.update_cultural_knowledge:
        log_debug("Creating cultural knowledge.")
        agent.culture_manager.create_cultural_knowledge(message=run_messages.user_message.get_content_string())


async def acreate_cultural_knowledge(
    agent: Agent,
    run_messages: RunMessages,
):
    if run_messages.user_message is not None and agent.culture_manager is not None and agent.update_cultural_knowledge:
        log_debug("Creating cultural knowledge.")
        await agent.culture_manager.acreate_cultural_knowledge(message=run_messages.user_message.get_content_string())


async def astart_cultural_knowledge_task(
    agent: Agent,
    run_messages: RunMessages,
    existing_task: Optional[Task[None]],
) -> Optional[Task[None]]:
    """Cancel any existing cultural knowledge task and start a new one if conditions are met.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing the user message.
        existing_task: An existing cultural knowledge task to cancel before starting a new one.

    Returns:
        A new cultural knowledge task if conditions are met, None otherwise.
    """
    # Cancel any existing task from a previous retry attempt
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except CancelledError:
            pass

    # Create new task if conditions are met
    if run_messages.user_message is not None and agent.culture_manager is not None and agent.update_cultural_knowledge:
        log_debug("Starting cultural knowledge creation in background task.")
        return create_task(acreate_cultural_knowledge(agent, run_messages=run_messages))

    return None


def start_cultural_knowledge_future(
    agent: Agent,
    run_messages: RunMessages,
    existing_future: Optional[Future] = None,
) -> Optional[Future]:
    """Cancel any existing cultural knowledge future and start a new one if conditions are met.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing the user message.
        existing_future: An existing cultural knowledge future to cancel before starting a new one.

    Returns:
        A new cultural knowledge future if conditions are met, None otherwise.
    """
    # Cancel any existing future from a previous retry attempt
    # Note: cancel() only works if the future hasn't started yet
    if existing_future is not None and not existing_future.done():
        existing_future.cancel()

    # Create new future if conditions are met
    if run_messages.user_message is not None and agent.culture_manager is not None and agent.update_cultural_knowledge:
        log_debug("Starting cultural knowledge creation in background thread.")
        return agent.background_executor.submit(make_cultural_knowledge, agent, run_messages=run_messages)

    return None


def get_culture_knowledge(agent: Agent) -> Optional[List[CulturalKnowledge]]:
    """Get the cultural knowledge the agent has access to

    Args:
        agent: The Agent instance.

    Returns:
        Optional[List[CulturalKnowledge]]: The cultural knowledge.
    """
    if agent.culture_manager is None:
        return None

    return agent.culture_manager.get_all_knowledge()


async def aget_culture_knowledge(agent: Agent) -> Optional[List[CulturalKnowledge]]:
    """Get the cultural knowledge the agent has access to

    Args:
        agent: The Agent instance.

    Returns:
        Optional[List[CulturalKnowledge]]: The cultural knowledge.
    """
    if agent.culture_manager is None:
        return None

    return await agent.culture_manager.aget_all_knowledge()


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------


def process_learnings(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
) -> None:
    """Process learnings from conversation (runs in background thread)."""
    if agent._learning is None:
        return

    try:
        # Convert run messages to list format expected by LearningMachine
        messages = run_messages.messages if run_messages else []

        agent._learning.process(
            messages=messages,
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
            team_id=agent.team_id,
        )
        log_debug("Learning extraction completed.")
    except Exception as e:
        log_warning(f"Error processing learnings: {e}")


async def aprocess_learnings(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
) -> None:
    """Async process learnings from conversation."""
    if agent._learning is None:
        return

    try:
        messages = run_messages.messages if run_messages else []
        await agent._learning.aprocess(
            messages=messages,
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
            team_id=agent.team_id,
        )
        log_debug("Learning extraction completed.")
    except Exception as e:
        log_warning(f"Error processing learnings: {e}")


async def astart_learning_task(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
    existing_task: Optional[Task] = None,
) -> Optional[Task]:
    """Start learning extraction as async task.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing conversation.
        session: The agent session.
        user_id: The user ID for learning extraction.
        existing_task: An existing task to cancel before starting a new one.

    Returns:
        A new learning task if conditions are met, None otherwise.
    """
    # Cancel any existing task from a previous retry attempt
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except CancelledError:
            pass

    # Create new task if learning is enabled
    if agent._learning is not None:
        log_debug("Starting learning extraction as async task.")
        return create_task(
            aprocess_learnings(
                agent,
                run_messages=run_messages,
                session=session,
                user_id=user_id,
            )
        )

    return None


def start_learning_future(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
    existing_future: Optional[Future] = None,
) -> Optional[Future]:
    """Start learning extraction in background thread.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing conversation.
        session: The agent session.
        user_id: The user ID for learning extraction.
        existing_future: An existing future to cancel before starting a new one.

    Returns:
        A new learning future if conditions are met, None otherwise.
    """
    # Cancel any existing future from a previous retry attempt
    if existing_future is not None and not existing_future.done():
        existing_future.cancel()

    # Create new future if learning is enabled
    if agent._learning is not None:
        log_debug("Starting learning extraction in background thread.")
        return agent.background_executor.submit(
            process_learnings,
            agent,
            run_messages=run_messages,
            session=session,
            user_id=user_id,
        )

    return None
