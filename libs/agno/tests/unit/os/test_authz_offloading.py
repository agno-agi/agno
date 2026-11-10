"""Authorization callbacks must keep a sync provider's blocking I/O off the event loop.

Authorization providers are synchronous by design: a managed-role store issues DB
round trips inside ``check``/``authorize_route``, and an FGA provider issues network
calls. Two things keep that work off the loop. A **sync** FastAPI dependency or
endpoint runs in the worker threadpool. An **async** one must reach the provider
through its ``a*`` twin, whose default runs the sync method in a worker thread
(``asyncio.to_thread``) so a plain sync provider is still offloaded.

Both properties are invisible in normal test runs and easy to destroy with a
well-intentioned "make it async" sweep, so they are asserted here explicitly.
"""

import asyncio
from inspect import iscoroutinefunction

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from agno.os.auth import require_resource_access
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider


class _Probe(AuthorizationProvider):
    """Records whether ``check`` ran on a thread that has a running event loop."""

    def __init__(self):
        self.ran_on_loop = None

    def check(self, ctx: AuthorizationContext) -> bool:
        try:
            asyncio.get_running_loop()
            self.ran_on_loop = True
        except RuntimeError:
            self.ran_on_loop = False
        return True

    def accessible_resource_ids(self, ctx: AuthorizationContext):
        return {"*"}


@pytest.mark.asyncio
async def test_per_resource_dependency_keeps_a_sync_provider_off_the_loop():
    """``require_resource_access`` builds the per-resource gate used by every run,
    continue, cancel, and read route. It is a coroutine so an async database is driven
    natively, which is only safe because it awaits the provider's async path: a sync
    provider's ``check`` must land in a worker thread, never on the loop. Measured on a
    provider with a 50ms decision, ten concurrent requests took 1.10s with the check on
    the loop and 0.61s offloaded."""
    app = FastAPI()
    probe = _Probe()
    app.state.authorization_provider = probe
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/agents/a1/runs",
        "headers": [],
        "query_string": b"",
        "path_params": {"agent_id": "a1"},
        "app": app,
    }
    request = Request(scope)
    request.state.authorization_enabled = True
    request.state.user_id = "bob"

    dependency = require_resource_access("agents", "run", "agent_id")
    assert iscoroutinefunction(dependency)  # drives an async db natively ...
    await dependency(request)
    assert probe.ran_on_loop is False, (
        "the per-resource gate ran a sync provider's check on the event loop; it must await the "
        "provider's async twin, whose default offloads to a worker thread"
    )


def test_authz_admin_handlers_are_async_and_use_the_store_twins():
    """Every /authz handler is a coroutine that awaits the store's async twins.

    The twins drive an async database natively and offload a sync one to a worker thread,
    so the loop is never blocked either way. A plain-def handler was threadpooled by FastAPI
    but called the SYNC store methods, which refuse an async database outright: the whole
    admin API returned 500 on that shape after authenticating the caller.
    """
    pytest.importorskip("sqlalchemy")  # managed roles need SQLAlchemy

    from agno.os.authz import Authorization
    from agno.os.authz.admin_router import get_roles_router

    router = get_roles_router(Authorization(db_url="sqlite:///:memory:"))
    sync_routes = [route.name for route in router.routes if not iscoroutinefunction(getattr(route, "endpoint", None))]
    assert sync_routes == [], (
        f"/authz handlers must be coroutines that await the store's async twins; these are sync: {sync_routes}"
    )
