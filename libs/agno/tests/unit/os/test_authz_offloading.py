"""The authorization callbacks must stay synchronous so FastAPI threadpools them.

Authorization providers are synchronous by design: a managed-role store issues DB
round trips inside ``check``/``authorize_route``, and an FGA provider issues network
calls. FastAPI runs a **sync** dependency or endpoint in its worker threadpool, so
that I/O stays off the event loop; declaring the same callback ``async`` runs the
blocking work directly on the loop and serialises every other in-flight request
behind each authorization check.

That property is invisible in normal test runs and easy to destroy with a
well-intentioned "make it async" sweep, so it is asserted here explicitly. If one of
these ever needs to be a coroutine, it must ``await`` the provider through
``run_in_threadpool`` first -- see the offload sites in ``agno/os/service_accounts.py``.
"""

from inspect import iscoroutinefunction

from agno.os.auth import require_resource_access


def test_per_resource_dependency_is_sync():
    """``require_resource_access`` builds the per-resource gate used by every run,
    continue, cancel, and read route. Measured on a provider with a 50ms decision:
    ten concurrent requests took 1.10s as a coroutine and 0.61s as a plain def."""
    dependency = require_resource_access("agents", "run", "agent_id")
    assert not iscoroutinefunction(dependency), (
        "require_resource_access's dependency must stay a plain `def`: it awaits nothing, "
        "and the authorization provider it calls does blocking I/O. As `async def` that "
        "I/O runs on the event loop instead of FastAPI's threadpool."
    )


def test_authz_admin_handlers_are_sync():
    """The /authz admin API is threadpooled only because its handlers are plain defs.

    Every one of them calls the role/user store (DB round trips) with no await, so
    making any of them ``async`` would move that I/O onto the loop.
    """
    pytest_sqlalchemy = __import__("pytest").importorskip("sqlalchemy")
    assert pytest_sqlalchemy  # managed roles need SQLAlchemy

    from agno.os.authz.role_router import get_roles_router
    from agno.os.authz.role_store import ManagedRoleStore

    router = get_roles_router(ManagedRoleStore(db_url="sqlite:///:memory:"))
    coroutine_routes = [route.name for route in router.routes if iscoroutinefunction(getattr(route, "endpoint", None))]
    assert coroutine_routes == [], (
        f"/authz handlers must stay sync so FastAPI threadpools their DB access; "
        f"these became coroutines: {coroutine_routes}"
    )
