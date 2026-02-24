"""Public session accessors and management for Team."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    cast,
)

if TYPE_CHECKING:
    from agno.team.team import Team

from agno.db.base import SessionType
from agno.metrics import SessionMetrics
from agno.models.message import Message
from agno.run import RunStatus
from agno.run.team import TeamRunOutput
from agno.session import TeamSession, WorkflowSession
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
from agno.utils.log import log_debug, log_warning

# ---------------------------------------------------------------------------
# Session read / write
# ---------------------------------------------------------------------------


def get_session(
    team: "Team",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[TeamSession]:
    """Load a TeamSession from database.

    Args:
        session_id: The session_id to load from storage.
        user_id: The user_id for tenant isolation.

    Returns:
        TeamSession: The TeamSession loaded from the database or created if it does not exist.
    """
    from agno.team._init import _has_async_db
    from agno.team._storage import _read_session

    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load: str = session_id or team.session_id  # type: ignore[assignment]

    # If there is a cached session, return it
    if team.cache_session and hasattr(team, "_cached_session") and team._cached_session is not None:
        if team._cached_session.session_id == session_id_to_load and (
            user_id is None or team._cached_session.user_id == user_id
        ):
            return team._cached_session

    if _has_async_db(team):
        raise ValueError("Cannot use sync get_session() with an async database. Use aget_session() instead.")

    # Load and return the session from the database
    if team.db is not None:
        loaded_session = None
        # We have a standalone team, so we are loading a TeamSession
        if team.workflow_id is None:
            loaded_session = cast(TeamSession, _read_session(team, session_id=session_id_to_load, user_id=user_id))
        # We have a workflow team, so we are loading a WorkflowSession
        else:
            loaded_session = cast(  # type: ignore[assignment]
                WorkflowSession,
                _read_session(
                    team,
                    session_id=session_id_to_load,
                    session_type=SessionType.WORKFLOW,
                    user_id=user_id,
                ),
            )

        # Cache the session if relevant
        if loaded_session is not None and team.cache_session:
            team._cached_session = loaded_session

        return loaded_session  # type: ignore[return-value]

    log_debug(f"TeamSession {session_id_to_load} not found in db")
    return None


async def aget_session(
    team: "Team",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[TeamSession]:
    """Load a TeamSession from database.

    Args:
        session_id: The session_id to load from storage.
        user_id: The user_id for tenant isolation.

    Returns:
        TeamSession: The TeamSession loaded from the database or created if it does not exist.
    """
    from agno.team._init import _has_async_db
    from agno.team._storage import _aread_session, _read_session

    if not session_id and not team.session_id:
        raise Exception("No session_id provided")

    session_id_to_load: str = session_id or team.session_id  # type: ignore[assignment]

    # If there is a cached session, return it
    if team.cache_session and hasattr(team, "_cached_session") and team._cached_session is not None:
        if team._cached_session.session_id == session_id_to_load and (
            user_id is None or team._cached_session.user_id == user_id
        ):
            return team._cached_session

    # Load and return the session from the database
    if team.db is not None:
        loaded_session = None
        # We have a standalone team, so we are loading a TeamSession
        if team.workflow_id is None:
            if _has_async_db(team):
                loaded_session = cast(
                    TeamSession, await _aread_session(team, session_id=session_id_to_load, user_id=user_id)
                )  # type: ignore[arg-type]
            else:
                loaded_session = cast(TeamSession, _read_session(team, session_id=session_id_to_load, user_id=user_id))
        # We have a workflow team, so we are loading a WorkflowSession
        else:
            if _has_async_db(team):
                loaded_session = cast(  # type: ignore[assignment]
                    WorkflowSession,
                    await _aread_session(
                        team,
                        session_id=session_id_to_load,
                        session_type=SessionType.WORKFLOW,
                        user_id=user_id,
                    ),
                )
            else:
                loaded_session = cast(  # type: ignore[assignment]
                    WorkflowSession,
                    _read_session(
                        team,
                        session_id=session_id_to_load,
                        session_type=SessionType.WORKFLOW,
                        user_id=user_id,
                    ),
                )

        # Cache the session if relevant
        if loaded_session is not None and team.cache_session:
            team._cached_session = loaded_session

        return loaded_session  # type: ignore[return-value]

    log_debug(f"TeamSession {session_id_to_load} not found in db")
    return None


def save_session(team: "Team", session: TeamSession) -> None:
    """
    Save the TeamSession to storage

    Args:
        session: The TeamSession to save.
    """
    from agno.team._init import _has_async_db
    from agno.team._run import _scrub_member_responses
    from agno.team._storage import _upsert_session

    if _has_async_db(team):
        raise ValueError("Cannot use sync save_session() with an async database. Use asave_session() instead.")

    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if session.session_data is not None and isinstance(session.session_data.get("session_state"), dict):
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)

        # scrub the member responses based on storage settings
        if session.runs is not None:
            for run in session.runs:
                if hasattr(run, "member_responses"):
                    if not team.store_member_responses:
                        # Remove all member responses
                        run.member_responses = []
                    else:
                        # Scrub individual member responses based on their storage flags
                        _scrub_member_responses(team, run.member_responses)
        _upsert_session(team, session=session)
        log_debug(f"Created or updated TeamSession record: {session.session_id}")


async def asave_session(team: "Team", session: TeamSession) -> None:
    """
    Save the TeamSession to storage

    Args:
        session: The TeamSession to save.
    """
    from agno.team._init import _has_async_db
    from agno.team._run import _scrub_member_responses
    from agno.team._storage import _aupsert_session, _upsert_session

    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if session.session_data is not None and isinstance(session.session_data.get("session_state"), dict):
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)

        # scrub the member responses based on storage settings
        if session.runs is not None:
            for run in session.runs:
                if hasattr(run, "member_responses"):
                    if not team.store_member_responses:
                        # Remove all member responses
                        run.member_responses = []
                    else:
                        # Scrub individual member responses based on their storage flags
                        _scrub_member_responses(team, run.member_responses)

        if _has_async_db(team):
            await _aupsert_session(team, session=session)
        else:
            _upsert_session(team, session=session)
        log_debug(f"Created or updated TeamSession record: {session.session_id}")


# ---------------------------------------------------------------------------
# Session name
# ---------------------------------------------------------------------------


def generate_session_name(team: "Team", session: TeamSession, _retries: int = 0) -> str:
    """
    Generate a name for the team session

    Args:
        session: The TeamSession to generate a name for.
        _retries: Internal retry counter (do not set manually).
    Returns:
        str: The generated session name.
    """
    max_retries = 3

    if team.model is None:
        raise Exception("Model not set")

    gen_session_name_prompt = "Team Conversation\n"

    # Get team session messages for generating the name
    messages_for_generating_session_name = session.get_messages()

    for message in messages_for_generating_session_name:
        gen_session_name_prompt += f"{message.role.upper()}: {message.content}\n"

    gen_session_name_prompt += "\n\nTeam Session Name: "

    system_message = Message(
        role=team.system_message_role,
        content="Please provide a suitable name for this conversation in maximum 5 words. "
        "Remember, do not exceed 5 words.",
    )
    user_message = Message(role="user", content=gen_session_name_prompt)
    generate_name_messages = [system_message, user_message]

    # Generate name
    generated_name = team.model.response(messages=generate_name_messages)
    content = generated_name.content
    if content is None:
        if _retries < max_retries:
            from agno.utils.log import log_error

            log_error("Generated name is None. Trying again.")
            return generate_session_name(team, session=session, _retries=_retries + 1)
        from agno.utils.log import log_error

        log_error("Generated name is None after max retries. Using fallback.")
        return "Team Session"
    if len(content.split()) > 15:
        if _retries < max_retries:
            from agno.utils.log import log_error

            log_error("Generated name is too long. Trying again.")
            return generate_session_name(team, session=session, _retries=_retries + 1)
        from agno.utils.log import log_error

        log_error("Generated name is too long after max retries. Using fallback.")
        return "Team Session"
    return content.replace('"', "").strip()


def set_session_name(
    team: "Team", session_id: Optional[str] = None, autogenerate: bool = False, session_name: Optional[str] = None
) -> TeamSession:
    """
    Set the session name and save to storage

    Args:
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        TeamSession: The updated session.
    """
    session_id = session_id or team.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        TeamSession,
        set_session_name_util(
            cast(Any, team),
            session_id=session_id,
            autogenerate=autogenerate,
            session_name=session_name,
        ),
    )


async def aset_session_name(
    team: "Team", session_id: Optional[str] = None, autogenerate: bool = False, session_name: Optional[str] = None
) -> TeamSession:
    """
    Set the session name and save to storage

    Args:
        session_id: The session ID to set the name for. If not provided, the current cached session ID is used.
        autogenerate: Whether to autogenerate the session name.
        session_name: The session name to set. If not provided, the session name will be autogenerated.
    Returns:
        TeamSession: The updated session.
    """
    session_id = session_id or team.session_id

    if session_id is None:
        raise Exception("Session ID is not set")

    return cast(
        TeamSession,
        await aset_session_name_util(
            cast(Any, team),
            session_id=session_id,
            autogenerate=autogenerate,
            session_name=session_name,
        ),
    )


def get_session_name(team: "Team", session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_name_util(cast(Any, team), session_id=session_id)


async def aget_session_name(team: "Team", session_id: Optional[str] = None) -> str:
    """
    Get the session name for the given session ID.

    Args:
        session_id: The session ID to get the name for. If not provided, the current cached session ID is used.
    Returns:
        str: The session name.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_name_util(cast(Any, team), session_id=session_id)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def get_session_state(team: "Team", session_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the session state for the given session ID.

    Args:
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return get_session_state_util(cast(Any, team), session_id=session_id)


async def aget_session_state(team: "Team", session_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the session state for the given session ID.

    Args:
        session_id: The session ID to get the state for. If not provided, the current cached session ID is used.
    Returns:
        Dict[str, Any]: The session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aget_session_state_util(cast(Any, team), session_id=session_id)


def update_session_state(team: "Team", session_state_updates: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return update_session_state_util(
        cast(Any, team), session_state_updates=session_state_updates, session_id=session_id
    )


async def aupdate_session_state(
    team: "Team", session_state_updates: Dict[str, Any], session_id: Optional[str] = None
) -> str:
    """
    Update the session state for the given session ID and user ID.
    Args:
        session_state_updates: The updates to apply to the session state. Should be a dictionary of key-value pairs.
        session_id: The session ID to update. If not provided, the current cached session ID is used.
    Returns:
        dict: The updated session state.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")
    return await aupdate_session_state_util(
        entity=cast(Any, team),
        session_state_updates=session_state_updates,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Session metrics
# ---------------------------------------------------------------------------


def get_session_metrics(team: "Team", session_id: Optional[str] = None) -> Optional[SessionMetrics]:
    """Get the session metrics for the given session ID.

    Args:
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[SessionMetrics]: The session metrics.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return get_session_metrics_util(cast(Any, team), session_id=session_id)


async def aget_session_metrics(team: "Team", session_id: Optional[str] = None) -> Optional[SessionMetrics]:
    """Get the session metrics for the given session ID.

    Args:
        session_id: The session ID to get the metrics for. If not provided, the current cached session ID is used.
    Returns:
        Optional[SessionMetrics]: The session metrics.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        raise Exception("Session ID is not set")

    return await aget_session_metrics_util(cast(Any, team), session_id=session_id)


def update_session_metrics(team: "Team", session: TeamSession, run_response: TeamRunOutput) -> None:
    """Calculate session metrics and write them to session_data.

    Converts run-level Metrics (details: Dict[str, List[ModelMetrics]]) to
    session-level SessionMetrics (details: List[ModelMetrics]) using
    SessionMetrics.accumulate_from_run().
    """
    from agno.team._storage import get_session_metrics_internal

    session_metrics = get_session_metrics_internal(team, session=session)
    if session_metrics is None:
        return
    if run_response.metrics is not None:
        session_metrics.accumulate_from_run(run_response.metrics)

    if session.session_data is not None:
        session.session_data["session_metrics"] = session_metrics.to_dict()


# ---------------------------------------------------------------------------
# Session delete
# ---------------------------------------------------------------------------


def delete_session(team: "Team", session_id: str, user_id: Optional[str] = None):
    """Delete the current session and save to storage"""
    if team.db is None:
        return

    team.db.delete_session(session_id=session_id, user_id=user_id)


async def adelete_session(team: "Team", session_id: str, user_id: Optional[str] = None):
    """Delete the current session and save to storage"""
    from agno.team._init import _has_async_db

    if team.db is None:
        return
    if _has_async_db(team):
        await team.db.delete_session(session_id=session_id, user_id=user_id)  # type: ignore
    else:
        team.db.delete_session(session_id=session_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Session messages / chat history
# ---------------------------------------------------------------------------


def get_session_messages(
    team: "Team",
    session_id: Optional[str] = None,
    member_ids: Optional[List[str]] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
    skip_member_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        session_id: The session ID to get the messages for. If not provided, the current cached session ID is used.
        member_ids: The ids of the members to get the messages from.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.
        skip_member_messages: Skip messages created by members of the team.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = get_session(team, session_id=session_id)
    if session is None:
        raise Exception("Session not found")

    return session.get_messages(
        team_id=team.id,
        member_ids=member_ids,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
        skip_member_messages=skip_member_messages,
    )


async def aget_session_messages(
    team: "Team",
    session_id: Optional[str] = None,
    member_ids: Optional[List[str]] = None,
    last_n_runs: Optional[int] = None,
    limit: Optional[int] = None,
    skip_roles: Optional[List[str]] = None,
    skip_statuses: Optional[List[RunStatus]] = None,
    skip_history_messages: bool = True,
    skip_member_messages: bool = True,
) -> List[Message]:
    """Get all messages belonging to the given session.

    Args:
        session_id: The session ID to get the messages for. If not provided, the current cached session ID is used.
        member_ids: The ids of the members to get the messages from.
        last_n_runs: The number of runs to return messages from, counting from the latest. Defaults to all runs.
        limit: The number of messages to return, counting from the latest. Defaults to all messages.
        skip_roles: Skip messages with these roles.
        skip_statuses: Skip messages with these statuses.
        skip_history_messages: Skip messages that were tagged as history in previous runs.
        skip_member_messages: Skip messages created by members of the team.

    Returns:
        List[Message]: The messages for the session.
    """
    session_id = session_id or team.session_id
    if session_id is None:
        log_warning("Session ID is not set, cannot get messages for session")
        return []

    session = await aget_session(team, session_id=session_id)
    if session is None:
        raise Exception("Session not found")

    return session.get_messages(
        team_id=team.id,
        member_ids=member_ids,
        last_n_runs=last_n_runs,
        limit=limit,
        skip_roles=skip_roles,
        skip_statuses=skip_statuses,
        skip_history_messages=skip_history_messages,
        skip_member_messages=skip_member_messages,
    )


def get_chat_history(
    team: "Team", session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Return the chat history (user and assistant messages) for the session.
    Use get_messages() for more filtering options.

    Args:
        session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.

    Returns:
        List[Message]: The chat history from the session.
    """
    return get_session_messages(
        team, session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"], skip_member_messages=True
    )


async def aget_chat_history(
    team: "Team", session_id: Optional[str] = None, last_n_runs: Optional[int] = None
) -> List[Message]:
    """Read the chat history from the session

    Args:
        session_id: The session ID to get the chat history for. If not provided, the current cached session ID is used.
    Returns:
        List[Message]: The chat history from the session.
    """
    return await aget_session_messages(
        team, session_id=session_id, last_n_runs=last_n_runs, skip_roles=["system", "tool"], skip_member_messages=True
    )


# ---------------------------------------------------------------------------
# Session summary
# ---------------------------------------------------------------------------


def get_session_summary(team: "Team", session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID.

    Args:
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.
    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else team.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = get_session(team, session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore


async def aget_session_summary(team: "Team", session_id: Optional[str] = None) -> Optional[SessionSummary]:
    """Get the session summary for the given session ID and user ID.

    Args:
        session_id: The session ID to get the summary for. If not provided, the current cached session ID is used.
    Returns:
        SessionSummary: The session summary.
    """
    session_id = session_id if session_id is not None else team.session_id
    if session_id is None:
        raise ValueError("Session ID is required")

    session = await aget_session(team, session_id=session_id)

    if session is None:
        raise Exception(f"Session {session_id} not found")

    return session.get_session_summary()  # type: ignore
