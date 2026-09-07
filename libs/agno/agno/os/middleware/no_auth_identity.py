"""No-auth identity middleware.

When an OS runs with a user directory and/or per-user isolation but NO authentication, there is no
verified token to key identity off. The directory and isolation still need SOMETHING, so this
middleware reads the caller's self-asserted ``user_id`` from the request and:

  * enables per-user isolation scoping for it (when ``user_isolation`` is on), so reads/writes get
    scoped exactly as the authenticated path does, and
  * provisions it into the directory (when ``auto_provision`` is on), so the roster fills in on any
    endpoint, not just runs.

This is ADVISORY, never enforced: the ``user_id`` is unverified (a caller could send any value), so
it is a convenience for local/demo use, not a security boundary. Enforcement is a property of
``AgentOS(authorization=True)`` with a verification key.

It reads only the query string, never the request body -- run POSTs carry ``user_id`` as a form
field and are handled at the run endpoint (which also stamps the run's own data by that id). Only
installed when no auth middleware is present (see AgentOS._add_auth_middleware / the no-auth branch).
"""

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from agno.os.middleware.user_scope import sync_directory_from_request


class NoAuthIdentityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, user_isolation: bool = False) -> None:
        super().__init__(app)
        self.user_isolation = user_isolation

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Defensive: never override a verified identity. There is none here (this only installs when
        # no auth middleware runs), but if one is added later this keeps the self-asserted path off.
        if not getattr(request.state, "authenticated", False):
            from agno.os.middleware.jwt import is_reserved_principal

            user_id = request.query_params.get("user_id")
            # A self-asserted query id must never claim a system-reserved principal (sa:*,
            # __scheduler__, __oauth__:) -- every other intake refuses these (jwt.py rejects such
            # JWT subs; resolve_run_user_id refuses them from the form). Without this guard a query
            # param like ?user_id=sa:victim would self-scope to that service account and route a
            # run into its history. Treat a reserved id as absent.
            if user_id and is_reserved_principal(user_id):
                user_id = None
            if user_id:
                if self.user_isolation:
                    # Mirror what the auth middleware sets so get_scoped_user_id scopes to this id.
                    request.state.user_id = user_id
                    request.state.user_isolation_enabled = True
                # Fill the roster from any endpoint (no-op when no directory / auto_provision off).
                sync_directory_from_request(request, user_id)
        return await call_next(request)
