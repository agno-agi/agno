"""Pins the ScopeAuthorizationProvider contract that keeps ``check()``'s deferral safe.

Review raised that ``check()`` returns True on an incomplete context (no ``resource_type`` /
``action``) -- a "fail-open". It is a deliberate DEFERRAL: ``check()`` is the per-resource
gate and cannot express a non-resource route (``/config``, ``/sessions``, ``/service-accounts``,
...) as a ``resource:action`` scope, so it returns True and leaves those routes to the ROUTE
gate (``authorize_route``), which does NOT defer -- it enforces the route's required scopes
directly, so an unscoped caller is denied. These tests pin both halves so the deferral can
never silently become a bypass, plus the resource scope-math the default provider preserves.
"""

import pytest

pytest.importorskip("agno.os.authz.scope_provider")

from agno.os.authz.provider import AuthorizationContext  # noqa: E402
from agno.os.authz.scope_provider import ScopeAuthorizationProvider  # noqa: E402

P = ScopeAuthorizationProvider()


def _ctx(**kw) -> AuthorizationContext:
    return AuthorizationContext(**kw)


class TestCheckDefersOnIncompleteContext:
    """A non-resource context cannot be expressed as a scope, so check() DEFERS (returns True)."""

    def test_no_resource_type_defers(self):
        assert P.check(_ctx(scopes=[], action="read")) is True

    def test_no_action_defers(self):
        assert P.check(_ctx(scopes=[], resource_type="agents")) is True


class TestRouteGateDoesNotDeferItEnforces:
    """The deferral is safe ONLY because the route gate enforces the route's required scopes
    directly: a non-resource route (resource_type/action unset) still needs its scopes, so an
    unscoped caller is denied rather than waved through."""

    def test_non_resource_route_requires_its_scopes(self):
        # e.g. a /service-accounts route mapped to ["service_accounts:read"], no resource_type
        assert P.authorize_route(_ctx(scopes=[]), ["service_accounts:read"]) is False
        assert P.authorize_route(_ctx(scopes=["service_accounts:read"]), ["service_accounts:read"]) is True

    def test_unmapped_public_route_has_no_required_scopes(self):
        assert P.authorize_route(_ctx(scopes=[]), []) is True


class TestResourceScopeMath:
    """For a resource check, the default provider allows iff the token carries the
    ``resource:action`` scope -- the behaviour it preserves from before the provider seam."""

    def test_matching_scope_allows(self):
        assert P.check(_ctx(scopes=["agents:run"], resource_type="agents", action="run")) is True

    def test_missing_scope_denies(self):
        assert P.check(_ctx(scopes=["agents:read"], resource_type="agents", action="run")) is False

    def test_per_resource_scope_is_scoped_to_that_resource(self):
        allow = _ctx(scopes=["agents:a1:run"], resource_type="agents", resource_id="a1", action="run")
        deny = _ctx(scopes=["agents:a1:run"], resource_type="agents", resource_id="a2", action="run")
        assert P.check(allow) is True
        assert P.check(deny) is False

    def test_wildcard_scope_covers_any_resource(self):
        assert (
            P.check(_ctx(scopes=["agents:*:run"], resource_type="agents", resource_id="anything", action="run")) is True
        )

    def test_admin_scope_bypasses(self):
        ctx = _ctx(scopes=["agent_os:admin"], resource_type="agents", action="run", admin_scope="agent_os:admin")
        assert P.check(ctx) is True


def test_provider_declares_it_enforces_token_scopes():
    """The scope provider IS the scope plane, so token scopes are authoritative under it --
    the flag the shared admin-gate helpers key off."""
    assert P.enforces_token_scopes is True
