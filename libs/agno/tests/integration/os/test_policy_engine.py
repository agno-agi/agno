"""The swappable-backend seam: ManagedRoleStore works with ANY PolicyEngine.

Proves the engine port by backing the store with a tiny in-memory engine (no
Casbin) and exercising the full agno-native surface + the provider through it.
"""

from typing import List, Set

from agno.os.authz.engine import PolicyEngine, ScopeEntry
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.role_store import ManagedRoleStore


class DictPolicyEngine(PolicyEngine):
    """Minimal dict-backed engine — exact scope-string matching, admin override.
    Enough to show the store/provider delegate correctly through the port."""

    def __init__(self):
        self._roles: dict = {}  # role -> {scope: effect}
        self._assign: dict = {}  # subject -> set[role]

    def set_role_scopes(self, role, entries: List[ScopeEntry]) -> None:
        self._roles[role] = {s: e for s, e in entries}

    def add_scope(self, role, scope, effect="allow") -> None:
        self._roles.setdefault(role, {})[scope] = effect

    def remove_scope(self, role, scope) -> None:
        self._roles.get(role, {}).pop(scope, None)

    def get_role_scopes(self, role) -> List[ScopeEntry]:
        return list(self._roles.get(role, {}).items())

    def remove_role(self, role) -> None:
        self._roles.pop(role, None)
        for s in self._assign.values():
            s.discard(role)

    def list_roles(self) -> List[str]:
        return list(self._roles)

    def assign(self, subject, role) -> None:
        self._assign.setdefault(subject, set()).add(role)

    def unassign(self, subject, role) -> None:
        self._assign.get(subject, set()).discard(role)

    def roles_of(self, subject) -> List[str]:
        return sorted(self._assign.get(subject, set()))

    def _scopes_for(self, subject, roles):
        rs = roles if roles else (self.roles_of(subject) if subject else [])
        out: dict = {}
        for r in rs:
            out.update(self._roles.get(r, {}))
        return out

    def check_scope(self, scope, *, subject=None, roles=None) -> bool:
        sc = self._scopes_for(subject, roles)
        return sc.get("agent_os:admin") == "allow" or sc.get(scope) == "allow"

    def check_resource(self, rt, rid, action, *, subject=None, roles=None) -> bool:
        if not rt or not action:
            return True
        return self.check_scope(f"{rt}:{action}", subject=subject, roles=roles)

    def accessible_resource_ids(self, rt, action, *, subject=None, roles=None) -> Set[str]:
        sc = self._scopes_for(subject, roles)
        if sc.get("agent_os:admin") == "allow" or sc.get(f"{rt}:{action}") == "allow":
            return {"*"}
        return set()


def test_store_runs_on_a_custom_engine_no_casbin():
    store = ManagedRoleStore(engine=DictPolicyEngine())  # no casbin involved

    # agno-native surface works through the port
    store.set_role_scopes("viewer", ["agents:read"], name="Viewer", description="read only")
    store.assign("bob", "viewer")
    assert store.roles_of("bob") == ["viewer"]
    assert store.list_roles() == ["viewer"]

    # metadata is store-owned (not the engine), so it works regardless of backend
    rec = store.get_role("viewer")
    assert rec["name"] == "Viewer" and rec["description"] == "read only"
    assert store.get_role_scope_entries("viewer") == [{"scope": "agents:read", "effect": "allow"}]

    # the provider delegates decisions to the engine
    prov = store.provider
    assert prov.check(AuthorizationContext(principal_id="bob", resource_type="agents", action="read")) is True
    assert prov.check(AuthorizationContext(principal_id="bob", resource_type="agents", action="run")) is False

    # admin gate delegates too
    assert store.can_manage("bob") is False
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("alice", "admin")
    assert store.can_manage("alice") is True


def test_patch_and_remove_through_engine():
    store = ManagedRoleStore(engine=DictPolicyEngine())
    store.create_role("editor", name="Editor")
    store.patch_role_scopes("editor", upsert=["agents:read", "agents:run"])
    store.patch_role_scopes("editor", remove=["agents:run"])
    assert [e["scope"] for e in store.get_role_scope_entries("editor")] == ["agents:read"]
    store.remove_role("editor")
    assert store.get_role("editor") is None
