"""Helpers for per-user data isolation at the route layer.

This module exposes a small set of helpers that routers call explicitly to
honour the opt-in ``AuthorizationConfig(user_isolation=True)`` contract:

    from agno.os.middleware.user_scope import (
        get_scoped_user_id,    # who, if anyone, are we scoping to?
        resolve_db_and_scope,  # fetch DB + the user_id to thread on reads
        enforce_owner_on_entity,  # coerce/validate user_id on writes
    )

The framework no longer wraps the DB in an adapter. Each router endpoint
threads ``user_id`` through the underlying ``BaseDb`` / ``AsyncBaseDb`` call
itself. The trade is fewer moving parts and clearer dispatch, at the cost
of a per-endpoint convention: every user-scoped read passes ``user_id``,
every write goes through ``enforce_owner_on_entity`` before persisting.

.. important::

   **Adding a new router endpoint that handles user-owned data?**

   You MUST call one of the scoping helpers (``get_scoped_user_id``,
   ``resolve_db_and_scope``, or ``apply_scope_to_kwargs``) and thread the
   resulting ``user_id`` into every DB read/write. Omitting this will
   silently bypass user isolation with no runtime error.

   Pattern for reads::

       scoped_user_id = get_scoped_user_id(request)
       db.get_sessions(user_id=scoped_user_id, ...)

   Pattern for writes::

       enforce_owner_on_entity(entity, request)
       db.upsert_session(entity)

Admin users (with the configured ``admin_scope``) and callers running with
isolation disabled get ``None`` from ``get_scoped_user_id`` — both helpers
become no-ops in that case, preserving the legacy unscoped behaviour.
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Tuple, Union

from fastapi import HTTPException, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.scopes import AgentOSScope
from agno.os.utils import get_db
from agno.remote.base import RemoteDb
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.agent import Agent, RemoteAgent
    from agno.agent.protocol import AgentProtocol
    from agno.os.app import AgentOS
    from agno.team import RemoteTeam, Team
    from agno.workflow import RemoteWorkflow, Workflow


ComponentType = Literal["agents", "teams", "workflows"]

# Reused error messages — referenced by route code AND tests.
SESSION_ID_REQUIRED = "session_id is required for this action"
WORKFLOW_ID_REQUIRED_RECONNECT = "workflow_id is required to reconnect to a workflow run"
SESSION_ID_REQUIRED_RECONNECT = "session_id is required to reconnect to a workflow run"
INSUFFICIENT_PERMISSIONS_WS_RECONNECT = "Insufficient permissions to reconnect to this workflow"


def _has_admin_scope(scopes: List[str], admin_scope: Optional[str] = None) -> bool:
    """Check if the user's scopes include admin access.

    Honours the configured ``admin_scope`` (set by JWTMiddleware via
    request.state.admin_scope) and falls back to the default ``agent_os:admin``.
    """
    return (admin_scope or AgentOSScope.ADMIN.value) in scopes


def get_scoped_user_id(request: Request) -> Optional[str]:
    """Get the user_id for data scoping from the request, or None if unscoped.

    Returns None (meaning "no filtering") when:
    - User isolation is not enabled (the opt-in
      ``AuthorizationConfig(user_isolation=True)`` flag is off).
    - No user_id in the JWT.
    - The user has admin scope (admins see all data).

    Returns the user_id string only when a regular (non-admin) user is
    authenticated AND user isolation is enabled.

    Use this in endpoints that thread user_id through internal method calls
    (e.g. agent.aget_run_output, aread_or_create_session).

    If the operator configured a custom ``admin_scope`` on JWTMiddleware, that
    value is honoured here too (read from ``request.state.admin_scope``).
    """
    # Opt-in gate: when user isolation is disabled, callers see the raw,
    # unscoped DB and route-level ownership checks behave as if no JWT user
    # were present. JWT/RBAC remain in force; they're orthogonal to scoping.
    if not getattr(request.state, "user_isolation_enabled", False):
        return None

    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None

    scopes: List[str] = getattr(request.state, "scopes", [])
    admin_scope_raw = getattr(request.state, "admin_scope", None)
    # Ignore non-string values (e.g. MagicMock auto-attrs in tests).
    admin_scope: Optional[str] = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    if _has_admin_scope(scopes, admin_scope=admin_scope):
        return None

    return user_id


async def resolve_db_and_scope(
    request: Request,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    db_id: Optional[str] = None,
    table: Optional[str] = None,
    *,
    fallback_user_id: Optional[str] = None,
) -> Tuple[Union[BaseDb, AsyncBaseDb, RemoteDb], Optional[str]]:
    """Look up the underlying DB and the ``user_id`` value to thread on reads.

    Returns a ``(db, user_id)`` tuple. ``user_id`` is the JWT sub when the
    caller is a non-admin scoped user; otherwise it falls back to
    ``fallback_user_id`` (typically a query-param ``user_id`` that admins use
    to filter, or the value the legacy unscoped path expected).

    Endpoints are expected to forward the returned ``user_id`` to the DB on
    every user-scoped read::

        db, user_id = await resolve_db_and_scope(request, dbs, db_id, table,
                                                  fallback_user_id=query_user_id)
        sessions, total = await db.get_sessions(user_id=user_id, ...)

    No wrapping, no virtual subclasses — the DB is the concrete backend the
    route was always going to call. ``RemoteDb`` is returned unchanged and
    receives ``user_id`` through the same forwarding kwarg.
    """
    db = await get_db(dbs, db_id, table)
    scoped_uid = get_scoped_user_id(request)
    if scoped_uid is not None:
        return db, scoped_uid
    return db, fallback_user_id


def apply_scope_to_kwargs(
    request: Request,
    kwargs: Optional[Dict[str, Any]] = None,
    *,
    fallback_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return ``kwargs`` with ``user_id`` set to the right value for the caller.

    Convenience for routers that prefer a single dict-spread call style::

        local_kwargs = apply_scope_to_kwargs(request, {"limit": 20, ...},
                                              fallback_user_id=query_user_id)
        rows, total = await db.get_user_memories(**local_kwargs)

    Mirrors ``resolve_db_and_scope`` — the JWT sub wins for non-admin scoped
    callers, otherwise ``fallback_user_id`` is used (so admin / unscoped
    callers keep their existing query-param filter behaviour).
    """
    out = dict(kwargs or {})
    scoped_uid = get_scoped_user_id(request)
    if scoped_uid is not None:
        out["user_id"] = scoped_uid
    elif fallback_user_id is not None:
        out["user_id"] = fallback_user_id
    return out


def enforce_owner_on_entity(request: Request, entity: Any, *, kind: str = "entity") -> None:
    """Coerce ``entity.user_id`` to the JWT sub for non-admin scoped callers.

    A no-op when isolation is disabled or the caller is admin. When the
    entity already carries a different ``user_id`` we warn loudly and rewrite
    — this matches the pre-existing adapter behaviour and keeps a single
    spoof attempt from poisoning storage. Routes that prefer a hard 404 on
    mismatch can compare before persisting and raise themselves.
    """
    scoped_uid = get_scoped_user_id(request)
    if scoped_uid is None:
        return
    current = getattr(entity, "user_id", None)
    if current is not None and current != scoped_uid:
        log_warning(
            f"user_scope: {kind} arrived with user_id={current!r} but the "
            f"caller is scoped to user_id={scoped_uid!r}. Coercing to the "
            f"authenticated user."
        )
    try:
        entity.user_id = scoped_uid  # type: ignore[attr-defined]
    except AttributeError:
        log_warning(f"user_scope: unable to coerce user_id on {kind} ({type(entity).__name__})")


# ----------------------------------------------------------------------------
# Run-ownership dependencies
#
# For endpoints keyed solely by run_id (cancel, continue) the cancellation
# manager has no user_id column, so ownership has to be verified at the router
# layer: load the session for {user_id, session_id} and ensure it contains the
# run. The three factories below return a FastAPI dependency that fetches the
# agent / team / workflow, enforces ownership for non-admin JWT callers, and
# returns the entity so the route body doesn't re-resolve it.
# ----------------------------------------------------------------------------


_RUN_COMPONENT_FIELDS: dict[ComponentType, str] = {
    "agents": "agent_id",
    "teams": "team_id",
    "workflows": "workflow_id",
}


def _component_field(component_type: Optional[ComponentType]) -> Optional[str]:
    """Return the session/run attribute name for ``component_type``, or None
    when no check was requested. An unknown component_type is treated as a
    programmer error and triggers fail-closed at the call sites.
    """
    if component_type is None:
        return None
    if component_type not in _RUN_COMPONENT_FIELDS:
        # Typo (e.g. "workflow" instead of "workflows") — fail closed at the
        # call site rather than silently skipping validation.
        raise ValueError(f"Unknown component_type: {component_type!r}")
    return _RUN_COMPONENT_FIELDS[component_type]


def run_matches_component(run, component_type: Optional[ComponentType], component_id: Optional[str]) -> bool:
    """Return True if ``run`` explicitly belongs to the given path component.

    Fails closed: a run that lacks the relevant component field is rejected,
    because nested member runs inside team/workflow sessions can have
    ambiguous attribution and must not be exposed through a sibling
    component's route. Unknown component_type values raise (fail-closed at
    the caller).
    """
    if not component_type or not component_id:
        return True
    field = _component_field(component_type)
    if field is None:
        return True
    return getattr(run, field, None) == component_id


def session_matches_component(session, component_type: Optional[ComponentType], component_id: Optional[str]) -> bool:
    """Return True if ``session`` explicitly belongs to the given path component.

    Fails closed (see ``run_matches_component`` for rationale). Unknown
    component_type values raise.
    """
    if not component_type or not component_id:
        return True
    field = _component_field(component_type)
    if field is None:
        return True
    return getattr(session, field, None) == component_id


def assert_session_matches_component(
    session,
    component_type: ComponentType,
    component_id: str,
    *,
    not_found_detail: str = "Session not found",
) -> None:
    """404 if ``session`` doesn't belong to the path component.

    Pure attribute check (no IO) — synchronous so callers don't have to
    ``await`` a function that can't actually suspend. Centralises the
    open-coded ``getattr(session, "<x>_id", None) != path_id`` check used
    across get/list/cancel/resume/continue routes and enforces fail-closed
    semantics in one place.
    """
    if not session_matches_component(session, component_type, component_id):
        raise HTTPException(status_code=404, detail=not_found_detail)


async def verify_run_in_session(
    entity,
    session_id: str,
    run_id: str,
    user_id: str,
    *,
    component_type: Optional[ComponentType] = None,
    component_id: Optional[str] = None,
) -> None:
    """Raise 404 if ``run_id`` isn't in a session owned by ``user_id``.

    When ``component_type`` and ``component_id`` are provided, also verifies:
      1. The loaded session belongs to that path component (a WorkflowSession
         cannot be reached through /agents/... even if a nested agent run
         lives inside it).
      2. The loaded run belongs to the same path component.

    Both checks fail closed when the component field is missing on the
    session/run.
    """
    session = await entity.aget_session(session_id=session_id, user_id=user_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")
    # Session must belong to the path component before we even look at runs.
    if not session_matches_component(session, component_type, component_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run = session.get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run_matches_component(run, component_type, component_id):
        # Mask existence — don't leak that the run lives under a different component.
        raise HTTPException(status_code=404, detail="Run not found")


async def verify_run_in_session_via_db(
    db: Union["BaseDb", "AsyncBaseDb", None],
    session_id: str,
    run_id: str,
    user_id: str,
    *,
    component_type: Optional[ComponentType] = None,
    component_id: Optional[str] = None,
) -> None:
    """Raise 404 if ``run_id`` isn't in a session owned by ``user_id``.

    Used by factory cancel routes that don't resolve an entity but still need
    to verify run ownership before applying a global cancellation intent.

    See ``verify_run_in_session`` for the session/run component checks.
    """
    if db is None:
        # No DB to verify against — fail closed.
        raise HTTPException(status_code=404, detail="Run not found")

    if isinstance(db, AsyncBaseDb):
        session = await db.get_session(session_id=session_id, user_id=user_id)
    else:
        session = db.get_session(session_id=session_id, user_id=user_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if not session_matches_component(session, component_type, component_id):
        raise HTTPException(status_code=404, detail="Run not found")

    get_run = getattr(session, "get_run", None)
    if get_run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run = get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run_matches_component(run, component_type, component_id):
        raise HTTPException(status_code=404, detail="Run not found")


def resolve_owned_agent(os: "AgentOS") -> Callable:
    """Return a FastAPI dependency yielding the Agent for a run the caller owns.

    For non-admin JWT callers the dependency also requires ``session_id`` as a
    query param and checks the run belongs to the caller's session; mismatches
    raise 404 so the existence of another user's run isn't leaked. Admins and
    unauthenticated callers bypass the ownership check entirely.
    """
    from agno.os.utils import get_agent_by_id

    async def dependency(
        request: Request,
        agent_id: str,
        run_id: str,
        session_id: Optional[str] = Query(
            default=None,
            description="Session ID the run belongs to. Required for non-admin JWT users.",
        ),
    ) -> "Union[Agent, RemoteAgent, AgentProtocol]":
        agent = get_agent_by_id(
            agent_id=agent_id,
            agents=os.agents,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
        )
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                agent,
                session_id,
                run_id,
                scoped_user_id,
                component_type="agents",
                component_id=agent_id,
            )
        return agent

    return dependency


def resolve_owned_team(os: "AgentOS") -> Callable:
    """Return a dependency yielding the Team for a run the caller owns.

    See ``resolve_owned_agent`` for behaviour.
    """
    from agno.os.utils import get_team_by_id

    async def dependency(
        request: Request,
        team_id: str,
        run_id: str,
        session_id: Optional[str] = Query(
            default=None,
            description="Session ID the run belongs to. Required for non-admin JWT users.",
        ),
    ) -> "Union[Team, RemoteTeam]":
        team = get_team_by_id(
            team_id=team_id,
            teams=os.teams,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                team,
                session_id,
                run_id,
                scoped_user_id,
                component_type="teams",
                component_id=team_id,
            )
        return team

    return dependency


def resolve_owned_workflow(os: "AgentOS") -> Callable:
    """Return a dependency yielding the Workflow for a run the caller owns.

    See ``resolve_owned_agent`` for behaviour.
    """
    from agno.os.utils import get_workflow_by_id

    async def dependency(
        request: Request,
        workflow_id: str,
        run_id: str,
        session_id: Optional[str] = Query(
            default=None,
            description="Session ID the run belongs to. Required for non-admin JWT users.",
        ),
    ) -> "Union[Workflow, RemoteWorkflow]":
        workflow = get_workflow_by_id(
            workflow_id=workflow_id,
            workflows=os.workflows,
            db=os.db,
            registry=os.registry,
            create_fresh=True,
        )
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if not session_id:
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
            await verify_run_in_session(
                workflow,
                session_id,
                run_id,
                scoped_user_id,
                component_type="workflows",
                component_id=workflow_id,
            )
        return workflow

    return dependency
