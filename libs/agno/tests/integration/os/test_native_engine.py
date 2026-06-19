"""NativePolicyEngine — agno's default managed-roles backend.

Covers the decision model directly (deny-overrides, object wildcards, the
scope<->policy read-back, roles-from-token vs stored subjects, transitive roles,
accessible-ids) and SQLAlchemy persistence. Managed roles always require a DB —
there is no in-memory mode, since an in-memory store can't stay consistent across
the workers/replicas an AgentOS deployment runs — so every test runs on a
throwaway SQLite DB and an unbound engine raises.
"""

import os
import tempfile

import pytest

pytest.importorskip("sqlalchemy")  # managed roles require a SQL DB; no in-memory mode

from agno.os.authz.native_engine import NativePolicyEngine  # noqa: E402


def _engine() -> NativePolicyEngine:
    """A throwaway file-backed SQLite engine. File (not ``:memory:``) so the same DB
    is visible across any threads, and each call is isolated to its own DB file."""
    fd, path = tempfile.mkstemp(suffix=".authz.db")
    os.close(fd)
    return NativePolicyEngine(db_url=f"sqlite:///{path}")


def test_basic_allow_and_deny_overrides():
    eng = _engine()
    eng.set_role_scopes(
        "member",
        [("agents:*:read", "allow"), ("agents:secret-agent:read", "deny")],
    )
    eng.assign("bob", "member")

    # allowed on a normal agent, denied on the explicitly-denied one (deny wins)
    assert eng.check_resource("agents", "public-agent", "read", subject="bob") is True
    assert eng.check_resource("agents", "secret-agent", "read", subject="bob") is False
    # action not granted at all
    assert eng.check_resource("agents", "public-agent", "run", subject="bob") is False
    # unknown subject
    assert eng.check_resource("agents", "public-agent", "read", subject="nobody") is False


def test_object_wildcard_matching():
    eng = _engine()
    eng.set_role_scopes("viewer", [("agents:*:read", "allow")])
    eng.assign("v", "viewer")
    # resource/* matches resource/<id> ...
    assert eng.check_resource("agents", "x", "read", subject="v") is True
    # ... but a per-id grant does not match a different id
    eng.set_role_scopes("runner", [("agents:a1:run", "allow")])
    eng.assign("r", "runner")
    assert eng.check_resource("agents", "a1", "run", subject="r") is True
    assert eng.check_resource("agents", "a2", "run", subject="r") is False


def test_admin_scope_allows_everything():
    eng = _engine()
    eng.set_role_scopes("admin", [("agent_os:admin", "allow")])
    eng.assign("alice", "admin")
    assert eng.check_resource("agents", "any", "run", subject="alice") is True
    assert eng.check_resource("teams", "any", "delete", subject="alice") is True
    assert eng.check_scope("sessions:delete", subject="alice") is True
    assert eng.accessible_resource_ids("agents", "read", subject="alice") == {"*"}


def test_scope_read_back_is_canonical():
    """agents:*:read and agents:read collapse to the same policy and read back as
    the global form — matching the documented (lossy) convention."""
    eng = _engine()
    eng.set_role_scopes("v", [("agents:*:read", "allow")])
    assert eng.get_role_scopes("v") == [("agents:read", "allow")]


def test_add_remove_and_effect_flip():
    eng = _engine()
    eng.add_scope("e", "agents:read")
    eng.add_scope("e", "agents:run")
    assert {s for s, _ in eng.get_role_scopes("e")} == {"agents:read", "agents:run"}
    # adding the same (obj, act) flips its effect rather than duplicating
    eng.add_scope("e", "agents:read", effect="deny")
    assert eng.get_role_scopes("e").count(("agents:read", "deny")) == 1
    assert ("agents:read", "allow") not in eng.get_role_scopes("e")
    eng.remove_scope("e", "agents:run")
    assert [s for s, _ in eng.get_role_scopes("e")] == ["agents:read"]


def test_roles_from_token_take_precedence():
    eng = _engine()
    eng.set_role_scopes("editor", [("agents:*:read", "allow"), ("agents:a1:run", "allow")])
    # subject has no stored assignment; role carried on the token authorizes
    assert eng.check_resource("agents", "a1", "run", subject="idp-user", roles=["editor"]) is True
    assert eng.check_resource("agents", "a1", "run", subject="idp-user") is False


def test_deny_on_one_token_role_does_not_veto_allow_on_another():
    """Per-root deny-overrides: a deny in role A must not cancel an allow in role B
    when both are carried on the token."""
    eng = _engine()
    eng.set_role_scopes("A", [("agents:a1:read", "deny")])
    eng.set_role_scopes("B", [("agents:*:read", "allow")])
    assert eng.check_resource("agents", "a1", "read", roles=["A", "B"]) is True
    # but a single role with both allow and deny IS deny-overridden
    eng.set_role_scopes("C", [("agents:*:read", "allow"), ("agents:a1:read", "deny")])
    assert eng.check_resource("agents", "a1", "read", roles=["C"]) is False


def test_transitive_role_assignment():
    eng = _engine()
    eng.set_role_scopes("super", [("agent_os:admin", "allow")])
    eng.assign("lead", "super")  # a role assigned to a role
    eng.assign("bob", "lead")
    assert eng.check_resource("agents", "x", "run", subject="bob") is True


def test_accessible_resource_ids_specific_and_wildcard():
    eng = _engine()
    eng.set_role_scopes("m", [("agents:a1:read", "allow"), ("agents:a2:read", "allow")])
    eng.assign("bob", "m")
    assert eng.accessible_resource_ids("agents", "read", subject="bob") == {"a1", "a2"}
    # a collection/global grant widens to wildcard
    eng.set_role_scopes("m", [("agents:*:read", "allow")])
    assert eng.accessible_resource_ids("agents", "read", subject="bob") == {"*"}
    # wrong action -> nothing
    assert eng.accessible_resource_ids("agents", "run", subject="bob") == set()


def test_remove_role_drops_policies_and_assignments():
    eng = _engine()
    eng.set_role_scopes("temp", [("agents:*:read", "allow")])
    eng.assign("bob", "temp")
    eng.remove_role("temp")
    assert eng.get_role_scopes("temp") == []
    assert eng.roles_of("bob") == []
    assert "temp" not in eng.list_roles()


def test_list_roles_includes_assignment_only_roles():
    eng = _engine()
    eng.assign("bob", "ghost")  # assigned but never given scopes
    assert "ghost" in eng.list_roles()


def test_unmappable_scope_is_not_satisfied():
    eng = _engine()
    eng.set_role_scopes("admin", [("agent_os:admin", "allow")])
    eng.assign("alice", "admin")
    # a malformed required scope returns False rather than raising
    assert eng.check_scope("not::a::valid::scope::x", subject="alice") is False


def test_persistence_round_trip(tmp_path):
    """Policies and assignments survive a fresh engine pointed at the same DB."""
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'policy.db'}"

    eng = NativePolicyEngine(db_url=url)
    eng.set_role_scopes("member", [("agents:*:read", "allow"), ("agents:a1:run", "allow")])
    eng.assign("bob", "member")
    assert eng.check_resource("agents", "a1", "run", subject="bob") is True

    # a brand-new engine on the same DB loads the persisted state
    eng2 = NativePolicyEngine(db_url=url)
    assert eng2.roles_of("bob") == ["member"]
    assert eng2.check_resource("agents", "a1", "run", subject="bob") is True
    assert {s for s, _ in eng2.get_role_scopes("member")} == {"agents:read", "agents:a1:run"}

    # mutations through the new engine also persist
    eng2.unassign("bob", "member")
    eng3 = NativePolicyEngine(db_url=url)
    assert eng3.roles_of("bob") == []


def test_list_filter_honours_deny_overrides_like_the_gate():
    """Regression: a wildcard allow + per-resource deny must hide the denied
    resource from list endpoints, matching the per-resource gate (deny-overrides).
    Previously accessible_resource_ids returned {'*'} and leaked the denied one."""
    from agno.os.authz.engine import EngineAuthorizationProvider
    from agno.os.authz.provider import AuthorizationContext

    class R:
        def __init__(self, rid):
            self.id = rid

    eng = _engine()
    # "read every agent EXCEPT the secret one"
    eng.set_role_scopes("analyst", [("agents:*:read", "allow"), ("agents:secret:read", "deny")])
    eng.assign("bob", "analyst")

    # engine surfaces the denied id even though the allow is a wildcard
    assert eng.accessible_resource_ids("agents", "read", subject="bob") == {"*"}
    assert eng.denied_resource_ids("agents", "read", subject="bob") == {"secret"}

    prov = EngineAuthorizationProvider(eng)
    resources = [R("public"), R("secret"), R("other")]
    # production list path builds the ctx with action=None (any-action visibility)
    list_ctx = AuthorizationContext(principal_id="bob", resource_type="agents")
    visible = {r.id for r in prov.filter_accessible(list_ctx, resources)}
    assert visible == {"public", "other"}  # secret carved out, not leaked

    # list visibility is consistent with the per-resource read gate
    for r in resources:
        gate = prov.check(
            AuthorizationContext(principal_id="bob", resource_type="agents", resource_id=r.id, action="read")
        )
        assert (r.id in visible) == gate


def test_denied_resource_ids_empty_without_denies():
    eng = _engine()
    eng.set_role_scopes("viewer", [("agents:*:read", "allow")])
    eng.assign("v", "viewer")
    assert eng.denied_resource_ids("agents", "read", subject="v") == set()


def test_db_backed_is_fresh_across_engines_no_cache(tmp_path):
    """Multi-container (#2): db-backed engines read fresh per decision, so a second
    engine (another worker/replica) sees a revocation immediately — no reload, no
    stale cache."""
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'roles.db'}"

    a = NativePolicyEngine(db_url=url)
    a.set_role_scopes("admin", [("agent_os:admin", "allow")])
    a.assign("bob", "admin")

    b = NativePolicyEngine(db_url=url)  # a second "worker"
    assert b.check_resource("agents", "x", "run", subject="bob") is True

    a.unassign("bob", "admin")  # revoked on the first worker
    # the second worker sees it on its very next decision — no reload() needed
    assert b.check_resource("agents", "x", "run", subject="bob") is False
    assert b.roles_of("bob") == []

    # a scope change is seen live too
    a.set_role_scopes("viewer", [("agents:*:read", "allow")])
    a.assign("carol", "viewer")
    assert b.check_resource("agents", "x", "read", subject="carol") is True
    assert b.get_role_scopes("viewer") == [("agents:read", "allow")]


def test_db_is_the_only_store_no_in_process_state(tmp_path):
    """The DB is the only source of truth — there are no in-process policy/grouping
    dicts to go stale (they were removed; a DB is required)."""
    pytest.importorskip("sqlalchemy")
    eng = NativePolicyEngine(db_url=f"sqlite:///{tmp_path / 'roles.db'}")
    eng.set_role_scopes("viewer", [("agents:*:read", "allow")])
    eng.assign("bob", "viewer")
    assert not hasattr(eng, "_policies") and not hasattr(eng, "_grouping")
    assert eng.is_bound is True
    assert eng.roles_of("bob") == ["viewer"]  # reads work (fresh from DB)


def test_unbound_engine_raises():
    """No DB anywhere -> the engine is unbound and every operation raises, rather
    than silently running an in-memory store that can't work across replicas."""
    eng = NativePolicyEngine()  # no db / db_url
    assert eng.is_bound is False
    with pytest.raises(RuntimeError, match="requires a SQL database"):
        eng.set_role_scopes("viewer", [("agents:*:read", "allow")])
    with pytest.raises(RuntimeError, match="requires a SQL database"):
        eng.check_resource("agents", "x", "read", subject="bob")
    with pytest.raises(RuntimeError, match="requires a SQL database"):
        eng.roles_of("bob")


def test_set_role_scopes_atomic_on_bad_scope(tmp_path):
    """#3: a bad scope mid-list must raise and leave the role's existing scopes
    intact (cache AND db), not half-applied."""
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'r.db'}"
    eng = NativePolicyEngine(db_url=url)
    eng.set_role_scopes("m", [("agents:*:read", "allow")])

    with pytest.raises(ValueError):
        eng.set_role_scopes("m", [("agents:*:run", "allow"), ("a:b:c:d", "allow")])  # 2nd is malformed

    assert eng.get_role_scopes("m") == [("agents:read", "allow")]  # unchanged
    # a fresh engine on the same DB agrees -> cache and DB never diverged
    assert NativePolicyEngine(db_url=url).get_role_scopes("m") == [("agents:read", "allow")]


def test_set_role_scopes_dedups_colliding_mappings(tmp_path):
    """#6: two scopes that map to the same (resource, action) must not raise an
    IntegrityError on persist; they collapse to one row (last effect wins)."""
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'r.db'}"
    eng = NativePolicyEngine(db_url=url)
    # agents:read and agents:*:read both -> ('agents/*', 'read')
    eng.set_role_scopes("m", [("agents:read", "allow"), ("agents:*:read", "allow")])
    assert eng.get_role_scopes("m") == [("agents:read", "allow")]
    assert NativePolicyEngine(db_url=url).get_role_scopes("m") == [("agents:read", "allow")]


def test_authorize_route_requires_all_scopes_and_no_blanket_allow():
    """#5: a route requiring >1 scope must satisfy ALL (was ANY). #4: a resource
    route with mixed actions (ctx.action=None) must not blanket-allow."""
    from agno.os.authz.engine import EngineAuthorizationProvider
    from agno.os.authz.provider import AuthorizationContext

    eng = _engine()
    eng.set_role_scopes("partial", [("sessions:read", "allow")])
    eng.set_role_scopes("full", [("sessions:read", "allow"), ("sessions:write", "allow")])
    eng.assign("p", "partial")
    eng.assign("f", "full")
    prov = EngineAuthorizationProvider(eng)

    # #5 — non-resource route requiring read AND write
    req = ["sessions:read", "sessions:write"]
    assert prov.authorize_route(AuthorizationContext(principal_id="p"), req) is False  # read only -> ALL fails
    assert prov.authorize_route(AuthorizationContext(principal_id="f"), req) is True

    # #4 — resource route, mixed actions => ctx.action is None; must require all, not allow
    eng.set_role_scopes("reader", [("agents:secret:read", "allow")])
    eng.assign("r", "reader")
    mixed = AuthorizationContext(principal_id="r", resource_type="agents", resource_id="secret", action=None)
    assert prov.authorize_route(mixed, ["agents:read", "agents:run"]) is False  # has read, not run
    eng.set_role_scopes("reader", [("agents:secret:read", "allow"), ("agents:secret:run", "allow")])
    assert prov.authorize_route(mixed, ["agents:read", "agents:run"]) is True


def test_effect_must_be_allow_or_deny_fail_closed():
    """A typo'd effect must raise, not silently become an allow (deny-overrides
    keys off the exact string 'deny')."""
    eng = _engine()
    with pytest.raises(ValueError):
        eng.add_scope("r", "agents:read", effect="denied")  # typo
    with pytest.raises(ValueError):
        eng.set_role_scopes("r", [("agents:read", "allw")])  # typo
    # canonical effects (any case) are accepted
    eng.add_scope("r", "agents:read", effect="DENY")
    assert eng.get_role_scopes("r") == [("agents:read", "deny")]
