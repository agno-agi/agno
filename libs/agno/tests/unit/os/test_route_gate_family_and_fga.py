"""Route-gate edge cases: foreign-family required scopes and multi-action FGA routes.

- The per-resource rewrite of a two-part required scope (``sessions:read`` on
  ``/agents/{id}/...`` becoming ``agents:<id>:read``) dropped the scope's own family, so a
  grant on the agent satisfied a requirement on sessions. Both the scope provider and the
  engine provider now check a foreign-family scope as written.
- The FGA provider's route gate deferred to ``check``, which treats a missing action as a
  non-resource question and allows. A custom mapping that requires two actions on a
  resource route therefore admitted anyone, anonymous callers included.
"""

import pytest

from agno.os.authz.fga import FGAAuthorizationProvider
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.scopes import has_required_scopes


class _Client:
    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.calls = []

    def check(self, user, relation, obj):
        self.calls.append((user, relation, obj))
        return (user, relation, obj) in self.allowed

    def list_objects(self, user, relation, object_type):
        return []


# --------------------------------------------------------------------------- scope provider


def test_foreign_family_required_scope_is_checked_as_written():
    # A grant on the agent does not stand in for sessions:read.
    assert not has_required_scopes(["agents:a1:read"], ["sessions:read"], resource_type="agents", resource_id="a1")
    # The global sessions grant does satisfy it, even on a per-resource path.
    assert has_required_scopes(["sessions:read"], ["sessions:read"], resource_type="agents", resource_id="a1")
    # Same-family scopes keep the per-resource rewrite.
    assert has_required_scopes(["agents:a1:run"], ["agents:run"], resource_type="agents", resource_id="a1")
    assert not has_required_scopes(["agents:a2:run"], ["agents:run"], resource_type="agents", resource_id="a1")


def test_legacy_alias_still_counts_as_the_same_family():
    assert has_required_scopes(["config:read"], ["system:read"], resource_type="config", resource_id="x")


def test_scope_provider_route_gate_requires_every_family():
    ctx = AuthorizationContext(scopes=["agents:a1:write"], resource_type="agents", resource_id="a1")
    assert not ScopeAuthorizationProvider().authorize_route(ctx, ["agents:write", "sessions:write"])
    ctx = AuthorizationContext(scopes=["agents:a1:write", "sessions:write"], resource_type="agents", resource_id="a1")
    assert ScopeAuthorizationProvider().authorize_route(ctx, ["agents:write", "sessions:write"])


# --------------------------------------------------------------------------- engine provider


@pytest.fixture
def engine_provider(tmp_path):
    pytest.importorskip("sqlalchemy")
    from agno.db.sqlite import SqliteDb
    from agno.os.authz._role_store import RoleStore
    from agno.os.authz.engine import EngineAuthorizationProvider

    store = RoleStore(db=SqliteDb(db_file=str(tmp_path / "fam.db")))
    store.set_role_scopes("agent-only", ["agents:a1:write"])
    store.set_role_scopes("both", ["agents:a1:write", "sessions:write"])
    store.assign("alice", "agent-only")
    store.assign("bob", "both")
    return EngineAuthorizationProvider(store._engine)


def test_engine_provider_checks_a_foreign_family_scope_as_written(engine_provider):
    ctx = AuthorizationContext(principal_id="alice", resource_type="agents", resource_id="a1", action="write")
    assert not engine_provider.authorize_route(ctx, ["sessions:write"])
    assert not engine_provider.authorize_route(ctx, ["agents:write", "sessions:write"])
    assert engine_provider.authorize_route(ctx, ["agents:write"])
    ctx = AuthorizationContext(principal_id="bob", resource_type="agents", resource_id="a1", action="write")
    assert engine_provider.authorize_route(ctx, ["agents:write", "sessions:write"])


@pytest.mark.asyncio
async def test_engine_provider_async_twin_matches(engine_provider):
    ctx = AuthorizationContext(principal_id="alice", resource_type="agents", resource_id="a1", action="write")
    assert not await engine_provider.aauthorize_route(ctx, ["sessions:write"])
    assert await engine_provider.aauthorize_route(ctx, ["agents:write"])


# --------------------------------------------------------------------------- FGA


def test_fga_multi_action_route_denies_anonymous_and_requires_every_action():
    client = _Client(allowed={("user:alice", "read", "agents:x"), ("user:alice", "run", "agents:x")})
    fga = FGAAuthorizationProvider(client)
    scopes = ["agents:read", "agents:run"]
    # No principal: never allowed.
    assert not fga.authorize_route(AuthorizationContext(resource_type="agents", resource_id="x"), scopes)
    # Both relationships held: allowed.
    assert fga.authorize_route(
        AuthorizationContext(principal_id="alice", resource_type="agents", resource_id="x"), scopes
    )
    # One relationship missing: denied.
    client.allowed.discard(("user:alice", "run", "agents:x"))
    assert not fga.authorize_route(
        AuthorizationContext(principal_id="alice", resource_type="agents", resource_id="x"), scopes
    )


def test_fga_single_action_route_is_unchanged():
    client = _Client(allowed={("user:alice", "run", "agents:x")})
    fga = FGAAuthorizationProvider(client)
    ctx = AuthorizationContext(principal_id="alice", resource_type="agents", resource_id="x", action="run")
    assert fga.authorize_route(ctx, ["agents:run"])
    assert not fga.authorize_route(AuthorizationContext(resource_type="config"), ["config:read"])
