"""Public session accessors and management for Team."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Union,
    cast,
)

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run.agent import RunOutput
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


def _scrub_tool_results_keeping_unresolved(run: Union[TeamRunOutput, "RunOutput"]) -> None:
    """Drop every stored tool-result message, keeping any call still awaiting one.

    ``scrub_tool_results_from_run_output`` drops every assistant message that
    made a call it removed. On a paused run that takes the message carrying the
    *pending* call with it whenever one assistant turn mixes a finished call
    with the gated one, leaving the resumed model nothing to answer. Here a
    resolved call is stripped out of the message it was made in instead, and
    the pending call survives."""
    from copy import copy

    if not run.messages:
        return
    if not any(message.role == "tool" for message in run.messages):
        return
    resolved = {message.tool_call_id for message in run.messages if message.role == "tool" and message.tool_call_id}
    kept = []
    for message in run.messages:
        if message.role == "tool":
            continue
        if message.role == "assistant" and message.tool_calls:
            remaining = [call for call in message.tool_calls if call.get("id") not in resolved]
            if not remaining:
                continue
            if len(remaining) != len(message.tool_calls):
                message = copy(message)
                message.tool_calls = remaining
        kept.append(message)
    run.messages = kept


def _resolve_spared_member(
    team: "Team", member_response: Union[TeamRunOutput, "RunOutput"]
) -> Optional[Union["Agent", "Team"]]:
    """Resolve the member that produced a spared response, by owning path.

    A run's member_responses belong to that team's DIRECT members, so the
    owner of a spared response is resolved among the direct members of the
    team level that carries it — never by a global search: sibling sub-teams
    may hold leaves with the same member id, and a tree-wide first match
    would apply the other leaf's storage flags. Among direct members an
    agent response resolves to an Agent and a team response to a Team.
    Only a response whose id matches no direct member at all (a
    caller-assembled tree that skips levels) falls back to the global
    search, which is then no worse than resolving it globally from the
    root."""
    from agno.run.agent import RunOutput
    from agno.team._tools import _find_member_by_id
    from agno.team.team import Team
    from agno.utils.team import get_member_id

    member_id = member_response.agent_id if isinstance(member_response, RunOutput) else member_response.team_id
    if not member_id:
        return None
    response_is_team = not isinstance(member_response, RunOutput)
    # Callable member lists resolve at run time; here (a storage scrub, no run
    # context) only a plain list can be searched — matching get_resolved_members.
    members = getattr(team, "members", None)
    if not isinstance(members, list):
        members = []
    direct_matches = [member for member in members if get_member_id(member) == member_id]
    for member in direct_matches:
        if isinstance(member, Team) == response_is_team:
            return member
    if direct_matches:
        return direct_matches[0]
    member_result = _find_member_by_id(team, member_id)
    return member_result[1] if member_result is not None else None


def _storage_view_of_spared_run(
    team: "Team",
    member_response: Union[TeamRunOutput, "RunOutput"],
    member: Optional[Union["Agent", "Team"]] = None,
) -> Union[TeamRunOutput, "RunOutput"]:
    """Apply a spared member's own storage flags to a copy of its paused run.

    A paused member run is kept out of the member-response scrub so
    continue_run can resume it after a reload. That exemption must not also
    carry the member's data past its own store_media / store_tool_messages /
    store_history_messages settings: the delegation path applies them to every
    member run it persists, and a run spared here is persisted the same way.

    ``member`` is the already-resolved owner when the caller knows it;
    otherwise it is resolved from ``team``'s direct members
    (_resolve_spared_member)."""
    from copy import copy

    from agno.utils.agent import (
        isolate_media_scrub_targets,
        scrub_history_messages_from_run_output,
        scrub_media_from_run_output,
    )

    if member is None:
        member = _resolve_spared_member(team, member_response)
    if member is None:
        # The owning member cannot be resolved (e.g. callable Team.members).
        # Store the strictest view: every storage flag treated as off, with the
        # paused-aware tool scrub so the pending call stays resumable.
        view = copy(member_response)
        isolate_media_scrub_targets(view)
        scrub_media_from_run_output(view)
        _scrub_tool_results_keeping_unresolved(view)
        scrub_history_messages_from_run_output(view)
        return view
    if member.store_media and member.store_tool_messages and member.store_history_messages:
        return member_response

    view = copy(member_response)
    # The spared run is shared with the live tree, and the media scrub rewrites
    # Message objects in place.
    isolate_media_scrub_targets(view)
    if not member.store_media:
        scrub_media_from_run_output(view)
    if not member.store_tool_messages:
        _scrub_tool_results_keeping_unresolved(view)
    if not member.store_history_messages:
        scrub_history_messages_from_run_output(view)
    return view


def _scrub_member_responses_keeping_paused(
    team: "Team",
    run: Union[TeamRunOutput, "RunOutput"],
) -> Union[TeamRunOutput, "RunOutput"]:
    """Return a storage view of the run with member responses removed at every
    nesting level, sparing paused ones: a paused member run is the resume
    state for continue_run after a session reload, and the save after it
    completes scrubs it. Completed responses inside a spared paused sub-team
    run are removed too, and a spared run still passes through its own member's
    storage flags.

    Copy-on-write: every level this rebuilds is shallow-copied, so the live run
    tree the caller holds keeps its member responses and its full messages."""
    from copy import copy

    from agno.team.team import Team

    spared = []
    for member_response in getattr(run, "member_responses", None) or []:
        if not getattr(member_response, "is_paused", False):
            continue
        # Resolve the owner at THIS level before recursing: the response tree
        # mirrors the team tree, and carrying the owning sub-team down keeps a
        # nested leaf resolving against its own branch — not a sibling's leaf
        # that shares its id.
        member = _resolve_spared_member(team, member_response)
        member_response = _storage_view_of_spared_run(team, member_response, member=member)
        if getattr(member_response, "member_responses", None):
            owning_team = member if isinstance(member, Team) else team
            member_response = _scrub_member_responses_keeping_paused(owning_team, member_response)
        spared.append(member_response)
    run = copy(run)
    run.member_responses = spared  # type: ignore[union-attr]
    return run


def save_session(team: "Team", session: TeamSession) -> None:
    """
    Save the TeamSession to storage

    Args:
        session: The TeamSession to save.
    """
    from copy import copy

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
        storage_session = session
        if session.runs is not None:
            if not team.store_member_responses:
                # Hand the DB a scrubbed view on a session of its own. Storing
                # the view on the caller's session instead — even briefly —
                # publishes it to everyone holding that session: with
                # cache_session the object is shared, so a concurrent
                # upsert_run would land in the throwaway list and a concurrent
                # save would capture it as the state to restore. The view is
                # also only ever a view: keeping it would freeze the stored
                # copy of a paused member run at PAUSED, and the resume
                # continues the live run, so a cached session would advertise
                # a pending approval on a finished run for good.
                storage_session = copy(session)
                storage_session.runs = [
                    _scrub_member_responses_keeping_paused(team, run) if hasattr(run, "member_responses") else run
                    for run in session.runs
                ]
            else:
                for run in session.runs:
                    if hasattr(run, "member_responses"):
                        # Scrub individual member responses based on their storage flags
                        _scrub_member_responses(team, run.member_responses)
        _upsert_session(team, session=storage_session)
        log_debug(f"Created or updated TeamSession record: {session.session_id}")


async def asave_session(team: "Team", session: TeamSession) -> None:
    """
    Save the TeamSession to storage

    Args:
        session: The TeamSession to save.
    """
    from copy import copy

    from agno.team._init import _has_async_db
    from agno.team._run import _scrub_member_responses
    from agno.team._storage import _aupsert_session, _upsert_session

    if team.db is not None and team.parent_team_id is None and team.workflow_id is None:
        if session.session_data is not None and isinstance(session.session_data.get("session_state"), dict):
            session.session_data["session_state"].pop("current_session_id", None)
            session.session_data["session_state"].pop("current_user_id", None)
            session.session_data["session_state"].pop("current_run_id", None)

        # scrub the member responses based on storage settings
        storage_session = session
        if session.runs is not None:
            if not team.store_member_responses:
                # See save_session: the scrubbed view is for the DB write only,
                # and it goes on a session of its own. Here the await makes the
                # window a real one — two overlapping saves on a shared session
                # would restore each other's snapshots out of order and leave
                # the scrubbed list live.
                storage_session = copy(session)
                storage_session.runs = [
                    _scrub_member_responses_keeping_paused(team, run) if hasattr(run, "member_responses") else run
                    for run in session.runs
                ]
            else:
                for run in session.runs:
                    if hasattr(run, "member_responses"):
                        # Scrub individual member responses based on their storage flags
                        _scrub_member_responses(team, run.member_responses)

        if _has_async_db(team):
            await _aupsert_session(team, session=storage_session)
        else:
            _upsert_session(team, session=storage_session)
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

    Accumulates metrics from the team leader's own model calls as well as
    all member agent/team responses (recursively for nested teams).
    """
    from agno.team._storage import get_session_metrics_internal

    session_metrics = get_session_metrics_internal(team, session=session)
    if session_metrics is None:
        return
    if run_response.metrics is not None:
        session_metrics.accumulate_from_run(run_response.metrics)

    # Accumulate metrics from member responses (agent and nested team runs)
    _accumulate_member_metrics(session_metrics, run_response.member_responses)

    if session.session_data is not None:
        session.session_data["session_metrics"] = session_metrics.to_dict()


def _accumulate_member_metrics(
    session_metrics: SessionMetrics,
    member_responses: "List",
) -> None:
    """Recursively accumulate metrics from member responses into session metrics."""
    for member_response in member_responses:
        if member_response.metrics is not None:
            session_metrics.accumulate_from_run(member_response.metrics)
        # Recurse into nested team member responses
        if isinstance(member_response, TeamRunOutput) and member_response.member_responses:
            _accumulate_member_metrics(session_metrics, member_response.member_responses)


# ---------------------------------------------------------------------------
# Session delete
# ---------------------------------------------------------------------------


def delete_session(team: "Team", session_id: str, user_id: Optional[str] = None):
    """Delete the current session and save to storage"""
    from agno.team._init import _has_async_db

    if _has_async_db(team):
        raise ValueError("Cannot use sync delete_session() with an async database. Use adelete_session() instead.")

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
        team,
        session_id=session_id,
        last_n_runs=last_n_runs,
        skip_roles=["system", "tool"],
        skip_member_messages=True,
        skip_statuses=[],
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
        team,
        session_id=session_id,
        last_n_runs=last_n_runs,
        skip_roles=["system", "tool"],
        skip_member_messages=True,
        skip_statuses=[],
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
