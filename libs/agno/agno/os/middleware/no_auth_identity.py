"""No-auth identity middleware.

When an OS runs with per-user isolation but NO authentication, there is no verified token to key
identity off. So this middleware reads the caller's self-asserted ``user_id`` from the request and
enables per-user isolation SCOPING for it (when ``user_isolation`` is on), so this request's own
reads are scoped as the authenticated path would.

It deliberately does NOT provision the directory. Scoping a request to a self-asserted id is
read-only; writing a directory row is not, and doing it from any endpoint on an open instance would
be an unauthenticated roster/audit-flooding primitive. No-auth provisioning is restricted to the run
endpoints (``sync_directory_from_request`` there), where there is at least intent to use the system.

This is ADVISORY, never enforced: the ``user_id`` is unverified (a caller could send any value), so
it is a convenience for local/demo use, not a security boundary. Enforcement is a property of
``AgentOS(authorization=True)`` with a verification key. A self-asserted id may never claim a
system-reserved principal (``sa:*`` / ``__scheduler__`` / ``__oauth__:``) -- those are refused.

It reads only the query string, never the request body -- run POSTs carry ``user_id`` as a form
field and are handled at the run endpoint. Only installed when no auth middleware is present (see
AgentOS._add_auth_middleware / the no-auth branch).
"""

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


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
            # Isolation SCOPING only -- deliberately NOT provisioning. Scoping this request's own
            # reads to a self-asserted id is read-only; WRITING a directory row is not. On an open
            # instance auto-provisioning from any endpoint would be an unauthenticated roster/audit
            # flooding primitive (a GET ?user_id=<random> inserts a row + audit event per id). So
            # no-auth provisioning is restricted to the run endpoints (sync_directory_from_request
            # there), where there is at least intent to use the system.
            if user_id and self.user_isolation:
                # Mirror what the auth middleware sets so get_scoped_user_id scopes to this id.
                request.state.user_id = user_id
                request.state.user_isolation_enabled = True
        return await call_next(request)
