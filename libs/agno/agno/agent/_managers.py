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
    from agno.metrics import RunMetrics

from agno.db.base import UserMemory
from agno.db.schemas.culture import CulturalKnowledge
from agno.models.message import Message
from agno.run.messages import RunMessages
from agno.session import AgentSession
from agno.utils.log import log_debug, log_warning

# Keep strong references to fire-and-forget learning tasks until they complete.
# asyncio only keeps weak references to tasks, so callers that intentionally do
# not await the returned task still need a durable owner.
_async_learning_tasks: set[Task] = set()

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def make_memories(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
) -> Optional[RunMetrics]:
    from agno.metrics import RunMetrics

    collector = RunMetrics()
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
            run_metrics=collector,
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
                    log_warning(f"Failed to validate message during memory update: {str(e)}")
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
                    messages=non_empty_messages, user_id=user_id, agent_id=agent.id, run_metrics=collector
                )  # type: ignore
            else:
                log_warning(
                    "Unable to add messages to memory: memory_manager not configured or update_memory_on_run is disabled"
                )
    return collector


async def amake_memories(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str] = None,
) -> Optional[RunMetrics]:
    from agno.metrics import RunMetrics

    collector = RunMetrics()
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
            run_metrics=collector,
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
                    log_warning(f"Failed to validate message during memory update: {str(e)}")
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
                    messages=non_empty_messages, user_id=user_id, agent_id=agent.id, run_metrics=collector
                )
            else:
                log_warning(
                    "Unable to add messages to memory: memory_manager not configured or update_memory_on_run is disabled"
                )
    return collector


async def astart_memory_task(
    agent: Agent,
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_task: Optional[Task],
) -> Optional[Task]:
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
    has_content = run_messages.user_message is not None or (
        run_messages.extra_messages is not None and len(run_messages.extra_messages) > 0
    )
    if (
        has_content
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
    has_content = run_messages.user_message is not None or (
        run_messages.extra_messages is not None and len(run_messages.extra_messages) > 0
    )
    if (
        has_content
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
) -> Optional[RunMetrics]:
    from agno.metrics import RunMetrics

    collector = RunMetrics()
    if run_messages.user_message is not None and agent.culture_manager is not None and agent.update_cultural_knowledge:
        log_debug("Creating cultural knowledge.")
        agent.culture_manager.create_cultural_knowledge(
            message=run_messages.user_message.get_content_string(),
            run_metrics=collector,
        )
    return collector


async def acreate_cultural_knowledge(
    agent: Agent,
    run_messages: RunMessages,
) -> Optional[RunMetrics]:
    from agno.metrics import RunMetrics

    collector = RunMetrics()
    if run_messages.user_message is not None and agent.culture_manager is not None and agent.update_cultural_knowledge:
        log_debug("Creating cultural knowledge.")
        await agent.culture_manager.acreate_cultural_knowledge(
            message=run_messages.user_message.get_content_string(),
            run_metrics=collector,
        )
    return collector


async def astart_cultural_knowledge_task(
    agent: Agent,
    run_messages: RunMessages,
    existing_task: Optional[Task],
) -> Optional[Task]:
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
) -> Optional[RunMetrics]:
    """Process learnings from conversation (runs in background thread)."""
    if agent._learning is None:
        return None

    from agno.metrics import RunMetrics

    collector = RunMetrics()
    try:
        # Snapshot: learning runs concurrently while the model call appends to the live list
        messages = list(run_messages.messages) if run_messages else []

        agent._learning.process(
            messages=messages,
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
            team_id=agent.team_id,
            run_metrics=collector,
        )
        log_debug("Learning extraction completed.")
    except Exception as e:
        log_warning(f"Error processing learnings: {str(e)}")
    return collector


async def aprocess_learnings(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
) -> Optional[RunMetrics]:
    """Async process learnings from conversation."""
    if agent._learning is None:
        return None

    from agno.metrics import RunMetrics

    collector = RunMetrics()
    try:
        # Snapshot: learning runs concurrently while the model call appends to the live list
        messages = list(run_messages.messages) if run_messages else []
        await agent._learning.aprocess(
            messages=messages,
            user_id=user_id,
            session_id=session.session_id if session else None,
            agent_id=agent.id,
            team_id=agent.team_id,
            run_metrics=collector,
        )
        log_debug("Learning extraction completed.")
    except Exception as e:
        log_warning(f"Error processing learnings: {str(e)}")
    return collector


async def astart_learning_task(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
    existing_task: Optional[Task] = None,
) -> Optional[Task]:
    """Start learning extraction as an async fire-and-forget task.

    The task is guarded by ``agent.learning_lock`` (an asyncio.Lock) so that
    learning tasks from consecutive runs are serialised in FIFO order,
    preventing concurrent read-modify-write races on shared learning data.

    The ``existing_task`` parameter is no longer used for cancellation — the
    lock guarantees ordering.  It is kept for API compatibility.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing conversation.
        session: The agent session.
        user_id: The user ID for learning extraction.
        existing_task: Ignored (kept for API compatibility).

    Returns:
        A new learning task if conditions are met, None otherwise.
    """
    # Create new task if learning is enabled
    if agent._learning is not None:
        log_debug("Starting learning extraction as async task (fire-and-forget).")
        # Snapshot messages for safety (run_messages may be mutated after return)
        messages = list(run_messages.messages) if run_messages else []
        session_id = session.session_id if session else None
        task = create_task(
            _aprocess_learnings_with_messages(
                agent,
                messages=messages,
                session_id=session_id,
                user_id=user_id,
            )
        )
        _async_learning_tasks.add(task)
        task.add_done_callback(_async_learning_tasks.discard)
        return task

    return None


def start_learning_future(
    agent: Agent,
    run_messages: RunMessages,
    session: AgentSession,
    user_id: Optional[str],
    existing_future: Optional[Future] = None,
) -> Optional[Future]:
    """Start learning extraction in a dedicated background thread (fire-and-forget).

    Uses the agent's dedicated ``_learning_executor`` (max_workers=1) so that
    learning tasks from consecutive runs are serialised in FIFO order, preventing
    concurrent read-modify-write races on shared learning data.

    The ``existing_future`` parameter is no longer used for cancellation — the
    dedicated executor guarantees ordering.  It is kept for API compatibility.

    Args:
        agent: The Agent instance.
        run_messages: The run messages containing conversation.
        session: The agent session.
        user_id: The user ID for learning extraction.
        existing_future: Ignored (kept for API compatibility).

    Returns:
        A new learning future if conditions are met, None otherwise.
    """
    # Create new future if learning is enabled
    if agent._learning is not None:
        log_debug("Starting learning extraction in background thread (fire-and-forget).")
        # Snapshot messages list for thread safety
        messages = list(run_messages.messages) if run_messages else []
        session_id = session.session_id if session else None
        return agent.learning_executor.submit(
            _process_learnings_with_messages,
            agent,
            messages=messages,
            session_id=session_id,
            user_id=user_id,
        )

    return None


def _process_learnings_with_messages(
    agent: Agent,
    messages: list,
    session_id: Optional[str],
    user_id: Optional[str],
) -> None:
    """Process learnings from pre-snapshot messages (runs in dedicated learning executor).

    This is the fire-and-forget entry point. It takes a pre-snapshot list of
    messages instead of a RunMessages object so it is safe to call after the
    run has completed and the RunMessages may no longer be valid.
    """
    if agent._learning is None:
        return

    try:
        agent._learning.process(
            messages=messages,
            user_id=user_id,
            session_id=session_id,
            agent_id=agent.id,
            team_id=agent.team_id,
        )
        log_debug("Learning extraction completed (fire-and-forget).")
    except Exception as e:
        log_warning(f"Error processing learnings: {str(e)}")


async def _aprocess_learnings_with_messages(
    agent: Agent,
    messages: list,
    session_id: Optional[str],
    user_id: Optional[str],
) -> None:
    """Async fire-and-forget learning with asyncio.Lock serialisation.

    Acquires ``agent.learning_lock`` before processing so that concurrent
    learning tasks from rapid-fire runs execute one at a time.
    """
    if agent._learning is None:
        return

    async with agent.learning_lock:
        try:
            await agent._learning.aprocess(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                agent_id=agent.id,
                team_id=agent.team_id,
            )
            log_debug("Learning extraction completed (async fire-and-forget).")
        except Exception as e:
            log_warning(f"Error processing learnings: {str(e)}")
