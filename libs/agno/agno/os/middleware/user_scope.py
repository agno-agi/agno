"""Helper for per-user data isolation via scoped DB wrappers.

When a JWT contains a user_id (sub claim), `get_user_scoped_db` wraps
the DB instance so all user-scoped queries (sessions, memory, traces)
are automatically filtered. Endpoints cannot accidentally leak data
across users.

Usage in a router:
    from agno.os.middleware.user_scope import get_user_scoped_db

    db = await get_user_scoped_db(request, dbs, db_id)
    # db.get_sessions() now auto-filters by user_id from the JWT
    # db.get_traces() now auto-filters by user_id from the JWT
    # db.get_knowledge_contents() passes through unmodified (no user_id column)
"""

from typing import Optional, Union

from fastapi import Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.user_scoped_db import AsyncUserScopedDb, UserScopedDb
from agno.os.utils import get_db
from agno.remote.base import RemoteDb
from agno.utils.log import log_debug


async def get_user_scoped_db(
    request: Request,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    db_id: Optional[str] = None,
    table: Optional[str] = None,
) -> Union[BaseDb, AsyncBaseDb, RemoteDb, UserScopedDb, AsyncUserScopedDb]:
    """Get a DB instance scoped to the authenticated user.

    If the request has a user_id in its state (set by JWT middleware),
    the returned DB will automatically filter all user-scoped queries.

    For RemoteDb instances, returns the db unmodified (the remote handles
    its own scoping via forwarded auth tokens).

    Args:
        request: The FastAPI request (must have request.state.user_id set by JWT middleware)
        dbs: The dbs dict from the router
        db_id: Optional database ID
        table: Optional table name

    Returns:
        A user-scoped DB wrapper, or the original DB if no user_id is present.
    """
    db = await get_db(dbs, db_id, table)

    user_id = getattr(request.state, "user_id", None)
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
