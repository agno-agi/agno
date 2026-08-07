"""Session read operations shared by the REST session router and the MCP tools.

Only the local-database branches live here: the logic that historically drifted
between surfaces (session-type auto-detection, run classification, sync-db
handling). ``RemoteDb`` calls are one-line proxies and stay at each surface,
which also owns forwarding the caller's Authorization header.

Sync ``BaseDb`` calls are offloaded to a threadpool so an async surface (MCP or
REST) never blocks its event loop on database I/O.
"""

from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.utils import detect_session_type
from agno.os.schema import RunSchema, TeamRunSchema, WorkflowRunSchema

AnyRunSchema = Union[RunSchema, TeamRunSchema, WorkflowRunSchema]


class SessionNotFoundError(Exception):
    """Raised when a session id does not resolve; surfaces map it to 404 / tool error."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session {session_id} not found")


class RunOwnershipError(Exception):
    """Raised when a run does not belong to the caller's session (masked as not-found)."""

    def __init__(self) -> None:
        super().__init__("Run not found")


async def verify_run_ownership(
    component: Any,
    *,
    session_id: str,
    run_id: str,
    user_id: str,
    component_type: Literal["agents", "teams", "workflows"],
    component_id: str,
) -> None:
    """Fail closed unless ``run_id`` lives in a ``user_id``-owned session for this component.

    Surface-agnostic twin of the REST ``verify_run_in_session`` (which raises
    ``HTTPException``); raises :class:`RunOwnershipError` so the MCP layer can present
    it as a tool error without importing HTTP types.
    """
    from agno.os.middleware.user_scope import run_matches_component, session_matches_component

    session = await component.aget_session(session_id=session_id, user_id=user_id)
    if session is None or not session_matches_component(session, component_type, component_id):
        raise RunOwnershipError()
    run = session.get_run(run_id=run_id)
    if run is None or not run_matches_component(run, component_type, component_id):
        raise RunOwnershipError()


async def get_sessions_page(
    db: Union[BaseDb, AsyncBaseDb],
    *,
    session_type: Optional[SessionType] = None,
    component_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_name: Optional[str] = None,
    limit: Optional[int] = 20,
    page: Optional[int] = 1,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[Any] = "desc",
) -> Tuple[List[Dict[str, Any]], int]:
    """One page of sessions as raw dicts plus the total count.

    Parameter types mirror the REST query params (all optional/defaulted, ``sort_order``
    accepts the ``SortOrder`` enum or a plain string) so both surfaces call this unchanged.
    """
    kwargs: Dict[str, Any] = dict(
        session_type=session_type,
        component_id=component_id,
        user_id=user_id,
        session_name=session_name,
        limit=limit,
        page=page,
        sort_by=sort_by,
        sort_order=sort_order,
        deserialize=False,
    )
    if isinstance(db, AsyncBaseDb):
        sessions, total_count = await db.get_sessions(**kwargs)
    else:
        sessions, total_count = await run_in_threadpool(lambda: db.get_sessions(**kwargs))
    return sessions, total_count  # type: ignore[return-value]


async def _get_session_dict(
    db: Union[BaseDb, AsyncBaseDb],
    *,
    session_id: str,
    session_type: Optional[SessionType],
    user_id: Optional[str],
) -> Tuple[Dict[str, Any], SessionType]:
    """Fetch a session as a raw dict, auto-detecting its type when not given.

    Auto-detection matters: local ``get_session`` does not filter by type in SQL,
    so a wrong caller-supplied default silently misparses rather than 404s.
    """
    if isinstance(db, AsyncBaseDb):
        session = await db.get_session(
            session_id=session_id, session_type=session_type, user_id=user_id, deserialize=False
        )
    else:
        session = await run_in_threadpool(
            lambda: db.get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=False,
            )
        )
    if not session:
        raise SessionNotFoundError(session_id)
    if session_type is None:
        session_type = SessionType(detect_session_type(session if isinstance(session, dict) else {}))
    return session, session_type  # type: ignore[return-value]


def classify_session_run(run: Dict[str, Any], session_type: SessionType) -> Optional[AnyRunSchema]:
    """Render one persisted run dict as the schema matching its actual shape.

    Team and workflow sessions can contain member/step runs of other kinds, so
    classification is per-run (by which component id the run carries), not
    per-session. Mirrors the REST behavior exactly, including dropping team-session
    runs that carry neither an agent_id nor a team_id (returns None).
    """
    if session_type == SessionType.AGENT:
        return RunSchema.from_dict(run)
    if session_type == SessionType.TEAM:
        if run.get("agent_id") is not None:
            return RunSchema.from_dict(run)
        if run.get("team_id") is not None:
            return TeamRunSchema.from_dict(run)
        return None
    if run.get("workflow_id") is not None:
        return WorkflowRunSchema.from_dict(run)
    if run.get("team_id") is not None:
        return TeamRunSchema.from_dict(run)
    return RunSchema.from_dict(run)


async def get_session_runs(
    db: Union[BaseDb, AsyncBaseDb],
    *,
    session_id: str,
    session_type: Optional[SessionType] = None,
    user_id: Optional[str] = None,
    created_after: Optional[int] = None,
    created_before: Optional[int] = None,
) -> List[AnyRunSchema]:
    """All runs of a session as schema objects, with type auto-detection.

    Raises :class:`SessionNotFoundError` when the session does not exist.
    """
    session, resolved_type = await _get_session_dict(
        db, session_id=session_id, session_type=session_type, user_id=user_id
    )

    runs = session.get("runs") or []
    filtered: List[Dict[str, Any]] = []
    for run in runs:
        created_at = run.get("created_at")
        # `is not None` (not truthiness): a bound of 0 is a real epoch timestamp, and a run
        # whose created_at is 0 must still be filtered rather than silently kept.
        if created_after is not None and created_at is not None and created_at < created_after:
            continue
        if created_before is not None and created_at is not None and created_at > created_before:
            continue
        filtered.append(run)

    classified = (classify_session_run(run, resolved_type) for run in filtered)
    return [run_schema for run_schema in classified if run_schema is not None]
