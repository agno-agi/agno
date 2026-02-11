"""Public session accessors and management for Agent."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    cast,
)
from uuid import uuid4

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.db.base import SessionType
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.session.summary import SessionSummary
from agno.utils.agent import (
    aget_session_metrics_util,
    aget_session_name_util,
    aget_session_state_util,
    aset_session_name_util,
    aupdate_session_state_util,
    get_session_metrics_util,
    get_session_name_util,
    get_session_state_util,
    set_session_name_util,
    update_session_state_util,
)
from agno.utils.log import log_debug, log_error, log_warning

# ---------------------------------------------------------------------------
# Session initialization
# ---------------------------------------------------------------------------


def initialize_session(
    agent: Agent,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Initialize the session for the agent."""

    if session_id is None:
        if agent.session_id:
            session_id = agent.session_id
        else:
            session_id = str(uuid4())
            # We make the session_id sticky to the agent instance if no session_id is provided
            agent.session_id = session_id

    log_debug(f"Session ID: {session_id}", center=True)

    # Use the default user_id when necessary
    if user_id is None or user_id == "":
        user_id = agent.user_id

    return session_id, user_id


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


def get_session(
    agent: Agent,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Load an AgentSession from database or cache.

    Args:
        agent: The Agent instance.
        session_id: The session_id to load from storage.

    Returns:
        AgentSession: The AgentSession loaded from the database/cache or None if not found.
    """
    from agno.agent import _init, _storage

    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load: str = session_id or agent.session_id  # type: ignore[assignment]

    # If there is a cached session, return it
    if agent.cache_session and hasattr(agent, "_cached_session") and agent._cached_session is not None:
        if agent._cached_session.session_id == session_id_to_load and (
            user_id is None or agent._cached_session.user_id == user_id
        ):
            return agent._cached_session

    if _init.has_async_db(agent):
        raise ValueError("Cannot use sync get_session() with an async database. Use aget_session() instead.")

    # Load and return the session from the database
    if agent.db is not None:
        loaded_session: Optional[Union[AgentSession, TeamSession, WorkflowSession]] = None

        # We have a standalone agent, so we are loading an AgentSession
        if agent.team_id is None and agent.workflow_id is None:
            loaded_session = cast(
                AgentSession,
                _storage.read_session(
                    agent, session_id=session_id_to_load, session_type=SessionType.AGENT, user_id=user_id
                ),  # type: ignore[arg-type]
            )

        # We have a team member agent, so we are loading a TeamSession
        if loaded_session is None and agent.team_id is not None:
            loaded_session = cast(
                TeamSession,
                _storage.read_session(
                    agent, session_id=session_id_to_load, session_type=SessionType.TEAM, user_id=user_id
                ),  # type: ignore[arg-type]
            )

        # We have a workflow member agent, so we are loading a WorkflowSession
        if loaded_session is None and agent.workflow_id is not None:
            loaded_session = cast(
                WorkflowSession,
                _storage.read_session(
                    agent, session_id=session_id_to_load, session_type=SessionType.WORKFLOW, user_id=user_id
                ),  # type: ignore[arg-type]
            )

        # Cache the session if relevant
        if loaded_session is not None and agent.cache_session:
            agent._cached_session = loaded_session  # type: ignore

        return loaded_session

    log_debug(f"Session {session_id_to_load} not found in db")
    return None


async def aget_session(
    agent: Agent,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
    """Load an AgentSession from database or cache.

    Args:
        agent: The Agent instance.
        session_id: The session_id to load from storage.

    Returns:
        AgentSession: The AgentSession loaded from the database/cache or None if not found.
    """
    from agno.agent import _storage

    if not session_id and not agent.session_id:
        raise Exception("No session_id provided")

    session_id_to_load: str = session_id or agent.session_id  # type: ignore[assignment]

    # If there is a cached session, return it
    if agent.cache_session and hasattr(agent, "_cached_session") and agent._cached_session is not None:
        if agent._cached_session.session_id == session_id_to_load and (
            user_id is None or agent._cached_session.user_id == user_id
        ):
            return agent._cached_session

    # Load and return the session from the database
    if agent.db is not None:
        loaded_session: Optional[Union[AgentSession, TeamSession, WorkflowSession]] = None

        # We have a standalone agent, so we are loading an AgentSession
        if agent.team_id is None and agent.workflow_id is None:
            loaded_session = cast(
                AgentSession,
                await _storage.aread_session(
                    agent, session_id=session_id_to_load, session_type=SessionType.AGENT, user_id=user_id
                ),  # type: ignore[arg-type]
            )

        # We have a team member agent, so we are loading a TeamSession
        if loaded_session is None and agent.team_id is not None:
            loaded_session = cast(
                TeamSession,
                await _storage.aread_session(
                    agent, session_id=session_id_to_load, session_type=SessionType.TEAM, user_id=user_id
                ),  # type: ignore[arg-type]
            )

        # We have a workflow member agent, so we are loading a WorkflowSession
        if loaded_session is None and agent.workflow_id is not None:
            loaded_session = cast(
                WorkflowSession,
                await _storage.aread_session(
                    agent, session_id=session_id_to_load, session_type=SessionType.WORKFLOW, user_id=user_id
                ),  # type: ignore[arg-type]
            )

        # Cache the session if relevant
        if loaded_session is not None and agent.cache_session:
            agent._cached_session = loaded_session  # type: ignore

        return loaded_session

    log_debug(f"AgentSession {session_id_to_load} not found in db")
    return None


def save_session(agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]) -> None:
    """
    Save the AgentSession to storage
    """
    from agno.agent import _init, _storage

    if _init.has_async_db(agent):
        raise ValueError("Cannot use sync save_session() with an async database. Use asave_session() instead.")
    # If the agent is a member of a team, do not save the session to the database
    if (
        agent.db is not None
        and agent.team_id is None
        and agent.workflow_id is None
        and session.session_data is not None
    ):
        if session.session_data is not None and isinstance(session.session_data.get("session_state"), dict):
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)

        _storage.upsert_session(agent, session=session)
        log_debug(f"Created or updated AgentSession record: {session.session_id}")


async def asave_session(agent: Agent, session: Union[AgentSession, TeamSession, WorkflowSession]) -> None:
    """
    Save the AgentSession to storage
    """
    from agno.agent import _init, _storage

    # If the agent is a member of a team, do not save the session to the database
    if (
        agent.db is not None
        and agent.team_id is None
        and agent.workflow_id is None
        and session.session_data is not None
    ):
        if session.session_data is not None and isinstance(session.session_data.get("session_state"), dict):
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)
        if _init.has_async_db(agent):
            await _storage.aupsert_session(agent, session=session)
        else:
            _storage.upsert_session(agent, session=session)
        log_debug(f"Created or updated AgentSession record: {session.session_id}")


def delete_session(agent: Agent, session_id: str, user_id: Optional[str] = None):
    """Delete the current session and save to storage"""
    if agent.db is None:
        return

    agent.db.delete_session(session_id=session_id, user_id=user_id)


async def adelete_session(agent: Agent, session_id: str, user_id: Optional[str] = None):
    """Delete the current session and save to storage"""
    from agno.agent import _init

    if agent.db is None:
        return
    if _init.has_async_db(agent):
        await agent.db.delete_session(session_id=session_id, user_id=user_id)  # type: ignore
    else:
        agent.db.delete_session(session_id=session_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Session name
# ---------------------------------------------------------------------------


def rename(agent: Agent, name: str, session_id: Optional[str] = None) -> None:
    """
    Rename the Agent and save to storage

    Args:
        agent: The Agent instance.
        name (str): The new name for the Agent.
        session_id (Optional[str]): The session_id of the session where to store the new name. If not provided, the current cached session ID is used.
    """
    from agno.agent import _init

    session_id = session_id or agent.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    if _init.has_async_db(agent):
        raise RuntimeError("`rename` is not supported with an async database. Please use `arename` instead.")

    session = get_session(agent, session_id=session_id)

    if session is None:
        raise Exception("Session not found")

    if not hasattr(session, "agent_data"):
        raise Exception("Session is not an AgentSession")

    # -*- Rename Agent
    agent.name = name

    if session.agent_data is not None:  # type: ignore
        session.agent_data["name"] = name  # type: ignore
    else:
        session.agent_data = {"name": name}  # type: ignore

    # -*- Save to storage
    save_session(agent, session=session)


def set_session_name(
    agent: Agent,
    session_id: Optional[str] = None,
    autogenerate: bool = False,
    session_name: Optional[str] = None,
) -> AgentSession:
    """
    Set the session name and save to storage

    Args:
        agent: The Agent instance.
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        AgentSession: The updated session.
    """
    session_id = session_id or agent.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        AgentSession,
        set_session_name_util(agent, session_id=session_id, autogenerate=autogenerate, session_name=session_name),
    )


async def aset_session_name(
    agent: Agent,
    session_id: Optional[str] = None,
    autogenerate: bool = False,
    session_name: Optional[str] = None,
) -> AgentSession:
    """
    Set the session name and save to storage

    Args:
        agent: The Agent instance.
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        AgentSession: The updated session.
    """
    session_id = session_id or agent.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        AgentSession,
        await aset_session_name_util(
            agent, session_id=session_id, autogenerate=autogenerate, session_name=session_name
        ),
    )


def generate_session_name(agent: Agent, session: AgentSession, max_retries: int = 3, _attempt: int = 0) -> str:
    """
    Generate a name for the session using the first 6 messages from the memory

    Args:
        agent: The Agent instance.
        session (AgentSession): The session to generate a name for.
        max_retries: Maximum number of retries if generation fails.
        _attempt: Current attempt number (used internally for recursion).
    Returns:
        str: The generated session name.
    """

    if agent.model is None:
        raise Exception("Model not set")

    gen_session_name_prompt = "Conversation\n"

    messages_for_generating_session_name = session.get_messages()

    for message in messages_for_generating_session_name:
        gen_session_name_prompt += f"{message.role.upper()}: {message.content}\n"

    gen_session_name_prompt += "\n\nConversation Name: "

    system_message = Message(
        role=agent.system_message_role,
        content="Please provide a suitable name for this conversation in maximum 5 words. "
        "Remember, do not exceed 5 words.",
    )
    user_message = Message(role=agent.user_message_role, content=gen_session_name_prompt)
    generate_name_messages = [system_message, user_message]

    # Generate name
    generated_name = agent.model.response(messages=generate_name_messages)
    content = generated_name.content
    if content is None:
        if _attempt >= max_retries:
            return "New Session"
        log_error("Generated name is None. Trying again.")
        return generate_session_name(agent, session=session, max_retries=max_retries, _attempt=_attempt + 1)

    if len(content.split()) > 5:
        if _attempt >= max_retries:
            return " ".join(content.split()[:5])
        log_error("Generated name is too long. It should be less than 5 words. Trying again.")
        return generate_session_name(agent, session=session, max_retries=max_retries, _attempt=_attempt + 1)
    return content.replace('"', "").strip()


def get_session_name(agent: Agent, session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_name_util(agent, session_id=session_id)


async def aget_session_name(agent: Agent, session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_name_util(agent, session_id=session_id)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def get_session_state(agent: Agent, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the session state for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_state_util(agent, session_id=session_id)


async def aget_session_state(agent: Agent, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the session state for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_state_util(agent, session_id=session_id)


def update_session_state(agent: Agent, session_state_updates: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        agent: The Agent instance.
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return update_session_state_util(agent, session_state_updates=session_state_updates, session_id=session_id)


async def aupdate_session_state(
    agent: Agent, session_state_updates: Dict[str, Any], session_id: Optional[str] = None
) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        agent: The Agent instance.
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aupdate_session_state_util(agent, session_state_updates=session_state_updates, session_id=session_id)


# ---------------------------------------------------------------------------
# Session metrics
# ---------------------------------------------------------------------------


def get_session_metrics(agent: Agent, session_id: Optional[str] = None) -> Optional[Metrics]:
    """Get the session metrics for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[Metrics]: The session metrics.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return get_session_metrics_util(agent, session_id=session_id)


async def aget_session_metrics(agent: Agent, session_id: Optional[str] = None) -> Optional[Metrics]:
    """Get the session metrics for the given session ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[Metrics]: The session metrics.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return await aget_session_metrics_util(agent, session_id=session_id)


def update_session_metrics(agent: Agent, session: AgentSession, run_response: RunOutput) -> None:
    """Calculate session metrics and write them to session_data."""
    from agno.agent._storage import get_session_metrics_internal

    session_metrics = get_session_metrics_internal(agent, session=session)
    # Add the metrics for the current run to the session metrics
    if session_metrics is None:
        return
    if run_response.metrics is not None:
        session_metrics += run_response.metrics
    session_metrics.time_to_first_token = None
    if session.session_data is not None:
        session.session_data["session_metrics"] = session_metrics


# ---------------------------------------------------------------------------
# Session messages
# ---------------------------------------------------------------------------


def get_session_messages(
    agent: Agent,
    session_id: Optional[str] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the messages for. If not provided, the latest used session ID is used.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = get_session(agent, session_id=session_id)
    if session is None:
        raise Exception("Session not found")

    # Handle the case in which the agent is reusing a team session
    if isinstance(session, TeamSession):
        return session.get_messages(
            member_ids=[agent.id] if agent.team_id and agent.id else None,
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=skip_roles,
            skip_statuses=skip_statuses,
            skip_history_messages=skip_history_messages,
        )

    return session.get_messages(
        # Only filter by agent_id if this is part of a team
        agent_id=agent.id if agent.team_id is not None else None,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
    )


async def aget_session_messages(
    agent: Agent,
    session_id: Optional[str] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the messages for. If not provided, the current cached session ID is used.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or agent.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = await aget_session(agent, session_id=session_id)
    if session is None:
        raise Exception("Session not found")

    # Handle the case in which the agent is reusing a team session
    if isinstance(session, TeamSession):
        return session.get_messages(
            member_ids=[agent.id] if agent.team_id and agent.id else None,
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=skip_roles,
            skip_statuses=skip_statuses,
            skip_history_messages=skip_history_messages,
        )

    # Only filter by agent_id if this is part of a team
    return session.get_messages(
        agent_id=agent.id if agent.team_id is not None else None,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
    )


def get_chat_history(
    agent: Agent, session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Return the chat history (user and assistant messages) for the session.
    Use get_messages() for more filtering options.

    Returns:
        A list of user and assistant Messages belonging to the session.
    """
    return get_session_messages(agent, session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"])


async def aget_chat_history(
    agent: Agent, session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Return the chat history (user and assistant messages) for the session.
    Use get_messages() for more filtering options.

    Returns:
        A list of user and assistant Messages belonging to the session.
    """
    return await aget_session_messages(
        agent, session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"]
    )


# ---------------------------------------------------------------------------
# Session summary
# ---------------------------------------------------------------------------


def get_session_summary(agent: Agent, session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.

    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else agent.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = get_session(agent, session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore


async def aget_session_summary(agent: Agent, session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID.

    Args:
        agent: The Agent instance.
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.
    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else agent.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = await aget_session(agent, session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore
