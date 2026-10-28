"""Bind verified request identity to SDK tool authorization."""

import json
from typing import Any, Dict, Optional

from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from agno.os.authz.provider import AuthorizationContext
from agno.run.authorization import AUTHORIZATION_HEADER, RunAuthorization, authorization_scope


def restore_authorization(app: Any, snapshot: Optional[Dict[str, Any]]) -> Optional[RunAuthorization]:
    from agno.os.auth import _default_authorization_provider, resolve_authorization_provider

    if snapshot is None:
        return None
    provider = (
        _default_authorization_provider() if snapshot.get("service_account") else resolve_authorization_provider(app)
    )
    authority = RunAuthorization(
        provider,
        AuthorizationContext(**snapshot["context"]),
        bool(snapshot.get("service_account")),
        enforce_tools=snapshot.get("enforce_tools", True),
    )

    if snapshot.get("company_routine"):
        from agno.company.routines import _RoutineAuthorization

        routine_authority = _RoutineAuthorization(
            None if snapshot.get("company_routine_unscoped") else authority,
            routine_id=snapshot.get("company_routine_id"),
            product_id=snapshot.get("company_product_id"),
        )
        routine_authority.context = authority.context
        return routine_authority
    if snapshot.get("company_executor"):
        from agno.company.execution import _ExecutorAuthorization

        return _ExecutorAuthorization(authority)
    return authority


def request_authorization(request: Any) -> Optional[RunAuthorization]:
    from agno.os.auth import _authorization_context, _provider_for

    if getattr(request.state, "is_internal_service", False):
        raw = request.headers.get(AUTHORIZATION_HEADER)
        # Only the authenticated executor may supply a persisted authority snapshot.
        if raw:
            snapshot = json.loads(raw)
            return restore_authorization(request.app, snapshot)
        if not getattr(request.state, "authorization_enabled", False):
            return None
        # Legacy schedules have no caller grants. Their target can still run, but
        # platform tools must not inherit the executor's broad transport scopes.
        from agno.os.auth import _default_authorization_provider

        return RunAuthorization(_default_authorization_provider(), AuthorizationContext(), enforce_tools=False)
    is_service_account = getattr(request.state, "service_account_name", None) is not None
    if not is_service_account and not getattr(request.state, "authorization_enabled", False):
        return None
    return RunAuthorization(
        _provider_for(request),
        _authorization_context(request),
        is_service_account,
        enforce_tools=False,
    )


class RunAuthorizationMiddleware:
    """Keep streaming, background tasks and WebSockets inside their caller scope.

    Resolve lazily: authentication dependencies and MCP identity bridges can
    establish identity after this middleware has entered the request.
    """

    def __init__(self, app: ASGIApp, authorization_app: Any):
        self.app = app
        self.authorization_app = authorization_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        # A mounted application may replace scope["app"]. Keep the provider of
        # the authenticating AgentOS while sharing the live verified state.
        scope.setdefault("state", {})
        request = HTTPConnection({**scope, "app": self.authorization_app})
        with authorization_scope(lambda: request_authorization(request)):
            await self.app(scope, receive, send)
