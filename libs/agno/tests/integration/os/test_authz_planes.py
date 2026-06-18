"""Two authz planes on one OS: token-scopes (operators) + the store (end users)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz._composite import CompositeAuthorizationProvider  # noqa: E402 (internal mechanism)
from agno.os.authz.provider import AuthorizationContext  # noqa: E402
from agno.os.authz.role_router import get_roles_router  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.authz.scope_provider import ScopeAuthorizationProvider  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "composite-secret-at-least-256-bits-long-padding-xxxxxxxx"
OS_ID = "composite-os"


def test_empty_providers_rejected():
    with pytest.raises(ValueError):
        CompositeAuthorizationProvider([])


def test_allows_via_either_plane():
    store = ManagedRoleStore()
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.assign("storeuser", "viewer")
    comp = CompositeAuthorizationProvider([ScopeAuthorizationProvider(), store.provider])

    # operator plane: scopes ride the token, nothing in the store for them
    operator = AuthorizationContext(principal_id="op", scopes=["agents:read"], resource_type="agents", action="read")
    assert comp.authorize_route(operator, ["agents:read"]) is True

    # end-user plane: no token scopes, the store grants it
    enduser = AuthorizationContext(
        principal_id="storeuser", scopes=[], resource_type="agents", resource_id="a1", action="read"
    )
    assert comp.authorize_route(enduser, ["agents:read"]) is True

    # neither plane grants -> denied
    nobody = AuthorizationContext(
        principal_id="nobody", scopes=[], resource_type="agents", resource_id="a1", action="read"
    )
    assert comp.authorize_route(nobody, ["agents:read"]) is False


def test_accessible_ids_union_with_wildcard_winning():
    store = ManagedRoleStore()
    store.set_role_scopes("one", ["agents:a1:read"])
    store.assign("u", "one")
    comp = CompositeAuthorizationProvider([ScopeAuthorizationProvider(), store.provider])

    # token gives a specific id, store gives another -> union
    ctx = AuthorizationContext(principal_id="u", scopes=["agents:a2:read"], resource_type="agents", action="read")
    assert comp.accessible_resource_ids(ctx) == {"a1", "a2"}

    # a global/wildcard scope on the token -> {"*"} wins
    ctx_all = AuthorizationContext(principal_id="u", scopes=["agents:read"], resource_type="agents", action="read")
    assert comp.accessible_resource_ids(ctx_all) == {"*"}


def _token(sub, scopes):
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": scopes, "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def test_both_planes_enforce_on_one_os_end_to_end():
    """One OS: an operator authorized by token scopes AND an end user authorized by
    the store both get in; an unknown caller is denied."""
    store = ManagedRoleStore()
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.assign("enduser", "viewer")  # end user known only to the store

    agent = Agent(id="research-agent", name="R", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            # public API: a LIST of providers -> allowed if any grants
            authorization_provider=[ScopeAuthorizationProvider(), store.provider],
        ),
    )
    client = TestClient(agent_os.get_app())
    hdr = lambda sub, scopes: {"Authorization": f"Bearer {_token(sub, scopes)}"}  # noqa: E731

    # operator: token carries the scope, no store entry
    assert client.get("/agents/research-agent", headers=hdr("op", ["agents:read"])).status_code == 200
    # end user: empty token scopes, store grants it
    assert client.get("/agents/research-agent", headers=hdr("enduser", [])).status_code == 200
    # neither: unknown caller, no scopes
    assert client.get("/agents/research-agent", headers=hdr("nobody", [])).status_code == 403


def test_admin_gate_accepts_admin_from_token_scope():
    """An operator whose token carries agent_os:admin can manage roles even though
    they have no admin assignment in the store (the cloud/operator plane)."""
    store = ManagedRoleStore()  # nobody is admin in the store
    agent = Agent(id="research-agent", name="R", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=[ScopeAuthorizationProvider(), store.provider],
        ),
    )
    app = agent_os.get_app()
    app.include_router(get_roles_router(store))
    client = TestClient(app)

    # admin via token scope -> can manage
    assert (
        client.get("/authz/roles", headers={"Authorization": f"Bearer {_token('op', ['agent_os:admin'])}"}).status_code
        == 200
    )
    # no admin scope and not in store -> denied
    assert (
        client.get("/authz/roles", headers={"Authorization": f"Bearer {_token('joe', ['agents:read'])}"}).status_code
        == 403
    )


def test_authorization_provider_rejects_a_string():
    """A list of providers is supported; a string is a mistake. The typed
    AuthorizationConfig field rejects it at construction (pydantic ValidationError,
    a ValueError), so it can never be mistaken for an iterable of characters."""
    with pytest.raises(ValueError, match="AuthorizationProvider"):
        AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            authorization_provider="ScopeAuthorizationProvider",  # oops, a string
        )


def test_composite_filter_accessible_unions_and_respects_per_plane_deny():
    """CompositeProvider.filter_accessible is a union (OR): each plane filters
    deny-aware within itself, and a resource is visible if ANY plane keeps it —
    so an engine deny carves the engine's grant but can't veto a scope-plane allow."""
    from agno.os.authz._composite import CompositeAuthorizationProvider
    from agno.os.authz.engine import EngineAuthorizationProvider
    from agno.os.authz.native_engine import NativePolicyEngine
    from agno.os.authz.provider import AuthorizationContext
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider

    class R:
        def __init__(self, rid):
            self.id = rid

    resources = [R("a"), R("secret"), R("b")]

    eng = NativePolicyEngine()
    eng.set_role_scopes("analyst", [("agents:*:read", "allow"), ("agents:secret:read", "deny")])
    eng.assign("bob", "analyst")
    engine_prov = EngineAuthorizationProvider(eng)

    # engine plane alone: deny-overrides carves out 'secret'
    ctx = AuthorizationContext(principal_id="bob", resource_type="agents")
    engine_only = CompositeAuthorizationProvider([engine_prov])
    assert {r.id for r in engine_only.filter_accessible(ctx, resources)} == {"a", "b"}

    # add a scope plane that grants all agents: union shows 'secret' again (OR;
    # the engine's deny is per-plane and can't veto another plane's grant)
    ctx_both = AuthorizationContext(principal_id="bob", scopes=["agents:read"], resource_type="agents")
    both = CompositeAuthorizationProvider([ScopeAuthorizationProvider(), engine_prov])
    assert {r.id for r in both.filter_accessible(ctx_both, resources)} == {"a", "secret", "b"}
