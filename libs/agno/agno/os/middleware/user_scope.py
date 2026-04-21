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

from typing import List, Optional, Union

from fastapi import Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.scopes import AgentOSScope
from agno.os.user_scoped_db import AsyncUserScopedDb, UserScopedDb
from agno.os.utils import get_db
from agno.remote.base import RemoteDb
from agno.utils.log import log_debug


def _has_admin_scope(scopes: List[str]) -> bool:
    """Check if the user's scopes include admin access."""
    return AgentOSScope.ADMIN.value in scopes


def get_scoped_user_id(request: Request) -> Optional[str]:
    """Get the user_id for data scoping from the request, or None if unscoped.

    Returns None (meaning "no filtering") when:
    - No user_id in the JWT
    - The user has admin scope (admins see all data)

    Returns the user_id string when a regular (non-admin) user is authenticated.

    Use this in endpoints that thread user_id through internal method calls
    (e.g. agent.aget_run_output, aread_or_create_session).
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None

    scopes: List[str] = getattr(request.state, "scopes", [])
    if _has_admin_scope(scopes):
        return None

    return user_id


async def get_user_scoped_db(
    request: Request,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    db_id: Optional[str] = None,
    table: Optional[str] = None,
) -> Union[BaseDb, AsyncBaseDb, RemoteDb, UserScopedDb, AsyncUserScopedDb]:
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

    if isinstance(db, AsyncBaseDb):
        log_debug(f"Creating async user-scoped DB wrapper for user_id={user_id}")
        return AsyncUserScopedDb(db, user_id)

    log_debug(f"Creating user-scoped DB wrapper for user_id={user_id}")
    return UserScopedDb(db, user_id)
