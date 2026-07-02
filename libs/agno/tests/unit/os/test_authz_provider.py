"""Unit tests for the AuthorizationProvider interface + default scope provider."""

import pytest

from agno.os.authz import (
    AuthorizationContext,
    AuthorizationProvider,
    ScopeAuthorizationProvider,
)


def ctx(**kw) -> AuthorizationContext:
    return AuthorizationContext(**kw)


class TestScopeProviderCheck:
    def setup_method(self):
        self.p = ScopeAuthorizationProvider()

    def test_global_scope_allows(self):
        assert self.p.check(ctx(scopes=["agents:run"], resource_type="agents", resource_id="a1", action="run"))

    def test_missing_scope_denies(self):
        assert not self.p.check(ctx(scopes=["agents:read"], resource_type="agents", resource_id="a1", action="run"))

    def test_per_resource_scope_allows_only_that_resource(self):
        c_ok = ctx(scopes=["agents:a1:run"], resource_type="agents", resource_id="a1", action="run")
        c_no = ctx(scopes=["agents:a1:run"], resource_type="agents", resource_id="a2", action="run")
        assert self.p.check(c_ok)
        assert not self.p.check(c_no)

    def test_admin_scope_bypasses(self):
        assert self.p.check(ctx(scopes=["agent_os:admin"], resource_type="agents", resource_id="x", action="run"))

    def test_custom_admin_scope_honoured(self):
        c = ctx(scopes=["ops:admin"], resource_type="agents", resource_id="x", action="run", admin_scope="ops:admin")
        assert self.p.check(c)

    def test_non_resource_check_allowed(self):
        # No resource_type/action → defer to route-level scope mappings.
        assert self.p.check(ctx(scopes=[]))


class TestScopeProviderAccessibleIds:
    def setup_method(self):
        self.p = ScopeAuthorizationProvider()

    def test_wildcard(self):
        assert self.p.accessible_resource_ids(ctx(scopes=["agents:*:read"], resource_type="agents", action="read")) == {"*"}

    def test_specific_ids(self):
        got = self.p.accessible_resource_ids(
            ctx(scopes=["agents:a1:read", "agents:a2:read"], resource_type="agents", action="read")
        )
        assert got == {"a1", "a2"}

    def test_admin_wildcard(self):
        assert self.p.accessible_resource_ids(ctx(scopes=["agent_os:admin"], resource_type="agents", action="read")) == {"*"}


class TestRequireDefault:
    def test_require_raises_permission_error(self):
        p = ScopeAuthorizationProvider()
        with pytest.raises(PermissionError):
            p.require(ctx(scopes=["agents:read"], resource_type="agents", resource_id="a1", action="run"))

    def test_require_passes_when_allowed(self):
        p = ScopeAuthorizationProvider()
        p.require(ctx(scopes=["agents:run"], resource_type="agents", resource_id="a1", action="run"))  # no raise


class TestFilterAccessibleDefault:
    class _R:
        def __init__(self, id):
            self.id = id

    def test_filters_to_accessible(self):
        p = ScopeAuthorizationProvider()
        resources = [self._R("a1"), self._R("a2"), self._R("a3")]
        c = ctx(scopes=["agents:a1:read", "agents:a3:read"], resource_type="agents", action="read")
        got = {r.id for r in p.filter_accessible(c, resources)}
        assert got == {"a1", "a3"}

    def test_wildcard_returns_all(self):
        p = ScopeAuthorizationProvider()
        resources = [self._R("a1"), self._R("a2")]
        c = ctx(scopes=["agent_os:admin"], resource_type="agents", action="read")
        assert len(p.filter_accessible(c, resources)) == 2


class TestCustomProviderContract:
    """A trivial custom provider only needs to implement check +
    accessible_resource_ids; require/filter_accessible come for free."""

    class AllowList(AuthorizationProvider):
        def __init__(self, allowed):
            self.allowed = allowed

        def check(self, c):
            return c.resource_id in self.allowed

        def accessible_resource_ids(self, c):
            return set(self.allowed)

    def test_custom_check(self):
        p = self.AllowList({"a1"})
        assert p.check(ctx(resource_type="agents", resource_id="a1", action="run"))
        assert not p.check(ctx(resource_type="agents", resource_id="a2", action="run"))

    def test_inherited_require(self):
        p = self.AllowList({"a1"})
        with pytest.raises(PermissionError):
            p.require(ctx(resource_type="agents", resource_id="a2", action="run"))
