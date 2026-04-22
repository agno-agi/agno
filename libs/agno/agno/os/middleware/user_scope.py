"""Helper for per-user data isolation via scoped DB wrappers.

When a JWT contains a user_id (sub claim), `get_user_scoped_db` wraps
the DB instance so all user-scoped queries (sessions, memory, traces)
are automatically filtered. Endpoints cannot accidentally leak data
across users.

Admin users (with agent_os:admin scope) bypass scoping and see all data.

Usage in a router:
    from agno.os.middleware.user_scope import get_user_scoped_db, get_scoped_user_id

    db = await get_user_scoped_db(request, dbs, db_id)
    # db.get_sessions() now auto-filters by user_id from the JWT
    # db.get_traces() now auto-filters by user_id from the JWT
    # db.get_knowledge_contents() passes through unmodified (no user_id column)

    # For endpoints that thread user_id manually (agents, teams, workflows):
    user_id = get_scoped_user_id(request)
    # Returns None for admins (no filtering), user_id for regular users
"""

from typing import TYPE_CHECKING, Callable, List, Optional, Union, cast

from fastapi import HTTPException, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.scopes import AgentOSScope
from agno.os.user_scoped_db import AsyncUserScopedDb, UserScopedDb
from agno.os.utils import get_db
from agno.remote.base import RemoteDb
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.agent import Agent, RemoteAgent
    from agno.os.app import AgentOS
    from agno.team import RemoteTeam, Team
    from agno.workflow import RemoteWorkflow, Workflow


def _has_admin_scope(scopes: List[str], admin_scope: Optional[str] = None) -> bool:
    """Check if the user's scopes include admin access.

    Honours the configured ``admin_scope`` (set by JWTMiddleware via
    request.state.admin_scope) and falls back to the default ``agent_os:admin``.
    """
    return (admin_scope or AgentOSScope.ADMIN.value) in scopes


def get_scoped_user_id(request: Request) -> Optional[str]:
    """Get the user_id for data scoping from the request, or None if unscoped.

    Returns None (meaning "no filtering") when:
    - No user_id in the JWT
    - The user has admin scope (admins see all data)

    Returns the user_id string when a regular (non-admin) user is authenticated.

    Use this in endpoints that thread user_id through internal method calls
    (e.g. agent.aget_run_output, aread_or_create_session).

    If the operator configured a custom ``admin_scope`` on JWTMiddleware, that
    value is honoured here too (read from ``request.state.admin_scope``).
    """
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


async def get_user_scoped_db(
    request: Request,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    db_id: Optional[str] = None,
    table: Optional[str] = None,
) -> Union[BaseDb, AsyncBaseDb, RemoteDb]:
    """Get a DB instance scoped to the authenticated user.

    If the request has a user_id in its state (set by JWT middleware)
    and the user is NOT an admin, the returned DB will automatically
    filter all user-scoped queries.

    Admin users (agent_os:admin scope) get the raw, unscoped DB.

    For RemoteDb instances, returns the db unmodified (the remote handles
    its own scoping via forwarded auth tokens).

    Args:
        request: The FastAPI request (must have request.state.user_id set by JWT middleware)
        dbs: The dbs dict from the router
        db_id: Optional database ID
        table: Optional table name

    Returns:
        A user-scoped DB wrapper, or the original DB if no user_id is present or user is admin.
    """
    db = await get_db(dbs, db_id, table)

    user_id = get_scoped_user_id(request)
    if not user_id:
        return db

    # RemoteDb handles its own auth via forwarded tokens
    if isinstance(db, RemoteDb):
        return db

    # The wrappers are registered as virtual subclasses of AsyncBaseDb / BaseDb
    # (see user_scoped_db.py), so `isinstance(wrapped, AsyncBaseDb)` returns
    # True at runtime. `cast` communicates that to mypy without inheriting
    # every abstract method on the wrapper.
    if isinstance(db, AsyncBaseDb):
        log_debug(f"Creating async user-scoped DB wrapper for user_id={user_id}")
        return cast(AsyncBaseDb, AsyncUserScopedDb(db, user_id))

    log_debug(f"Creating user-scoped DB wrapper for user_id={user_id}")
    return cast(BaseDb, UserScopedDb(db, user_id))


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


async def _verify_run_in_session(entity, session_id: str, run_id: str, user_id: str) -> None:
    """Raise 404 if ``run_id`` isn't in a session owned by ``user_id``."""
    session = await entity.aget_session(session_id=session_id, user_id=user_id)
    if session is None or session.get_run(run_id=run_id) is None:
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
    ) -> "Union[Agent, RemoteAgent]":
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
                raise HTTPException(status_code=400, detail="session_id is required for this action")
            await _verify_run_in_session(agent, session_id, run_id, scoped_user_id)
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
                raise HTTPException(status_code=400, detail="session_id is required for this action")
            await _verify_run_in_session(team, session_id, run_id, scoped_user_id)
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
                raise HTTPException(status_code=400, detail="session_id is required for this action")
            await _verify_run_in_session(workflow, session_id, run_id, scoped_user_id)
        return workflow

    return dependency
