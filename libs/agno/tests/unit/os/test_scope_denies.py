"""Unit tests for agno.os.scopes.apply_scope_denies: a token's denies claim removes grants."""

import pytest

from agno.os.scopes import (
    apply_scope_denies,
    get_accessible_resource_ids,
    get_default_scope_mappings,
    has_required_scopes,
)


class TestNoDenies:
    @pytest.mark.parametrize("denies", [None, []])
    def test_scopes_are_returned_unchanged(self, denies):
        scopes = ["agent_os:admin", "agents::run", "anything goes"]
        assert apply_scope_denies(scopes, denies) is scopes


class TestMalformedClaim:
    @pytest.mark.parametrize("denies", [{"agents": "run"}, 5, ["agents:run", 7], [None]])
    def test_non_string_list_grants_nothing(self, denies):
        assert apply_scope_denies(["agent_os:admin"], denies) == []

    @pytest.mark.parametrize("deny", ["*:delete", "agents:x:*", "tasks:delete ", "agents", "a:b:c:d"])
    def test_unparseable_deny_grants_nothing(self, deny):
        assert apply_scope_denies(["agent_os:admin", "tasks:read"], [deny]) == []

    def test_string_claim_is_one_deny(self):
        assert apply_scope_denies(["agents:read", "agents:run"], "agents:run") == ["agents:read"]


class TestGlobalAndWildcardDenies:
    def test_global_deny_removes_global_wildcard_and_per_id_allows(self):
        scopes = ["agents:run", "agents:*:run", "agents:x:run", "agents:read"]
        assert apply_scope_denies(scopes, ["agents:run"]) == ["agents:read"]

    def test_wildcard_deny_equals_global_deny(self):
        assert apply_scope_denies(["agents:run", "agents:x:run"], ["agents:*:run"]) == []

    def test_other_actions_and_families_are_kept(self):
        scopes = ["tasks:read", "tasks:write", "tasks:delete", "projects:delete"]
        assert apply_scope_denies(scopes, ["tasks:delete"]) == ["tasks:read", "tasks:write", "projects:delete"]

    def test_legacy_alias_is_matched_both_ways(self):
        assert apply_scope_denies(["system:read", "config:read"], ["config:read"]) == []
        assert apply_scope_denies(["config:read"], ["system:read"]) == []


class TestPerIdDenies:
    def test_removes_the_matching_per_id_allow_only(self):
        scopes = ["agents:x:run", "agents:y:run"]
        assert apply_scope_denies(scopes, ["agents:x:run"]) == ["agents:y:run"]

    def test_removes_the_broader_allow_that_covers_it(self):
        # "Every agent except x" cannot be written as scopes, so the broad grant goes.
        assert apply_scope_denies(["agents:*:run", "agents:run", "agents:y:run"], ["agents:x:run"]) == ["agents:y:run"]

    def test_listing_no_longer_returns_wildcard(self):
        scopes = apply_scope_denies(["agents:*:read", "agents:y:read"], ["agents:x:read"])
        assert get_accessible_resource_ids(scopes, "agents", action="read") == {"y"}


class TestAdmin:
    def test_any_deny_replaces_admin_with_known_scopes_minus_denied(self):
        scopes = apply_scope_denies(["agent_os:admin"], ["tasks:delete"])
        assert "agent_os:admin" not in scopes
        assert "tasks:delete" not in scopes
        assert {"tasks:read", "tasks:write", "agents:run", "service_accounts:write"} <= set(scopes)
        assert not has_required_scopes(scopes, ["tasks:delete"])
        assert has_required_scopes(scopes, ["tasks:write"])

    def test_expansion_covers_every_default_mapping_scope_except_denied(self):
        known = {s for required in get_default_scope_mappings(company=True).values() for s in required}
        scopes = apply_scope_denies(["agent_os:admin"], ["tasks:delete"])
        assert set(scopes) == known - {"tasks:delete", "agent_os:admin"}

    def test_known_scopes_override_the_default_expansion(self):
        scopes = apply_scope_denies(["agent_os:admin"], ["tasks:delete"], known_scopes=["custom:read", "tasks:delete"])
        assert scopes == ["custom:read"]

    def test_admin_deny_removes_admin_but_keeps_other_grants(self):
        assert apply_scope_denies(["agent_os:admin", "agents:read"], ["agent_os:admin"]) == ["agents:read"]

    def test_custom_admin_scope_is_expanded_and_can_be_denied(self):
        scopes = apply_scope_denies(["acme:root"], ["tasks:delete"], admin_scope="acme:root")
        assert "acme:root" not in scopes and "tasks:write" in scopes
        assert apply_scope_denies(["acme:root"], ["acme:root"], admin_scope="acme:root") == []
        # Either admin spelling in the denies revokes the configured admin.
        assert apply_scope_denies(["acme:root"], ["agent_os:admin"], admin_scope="acme:root") == []

    def test_default_admin_spelling_is_removed_under_a_custom_admin_scope(self):
        # Checks that pass no admin_scope (the approval-admin gate, for one) honour the
        # default spelling, so it must not survive a token with denies.
        scopes = apply_scope_denies(["agent_os:admin"], ["approvals:write"], admin_scope="acme:root")
        assert "agent_os:admin" not in scopes
        assert not has_required_scopes(scopes, ["approvals:write"])

    def test_default_admin_spelling_is_not_expanded_under_a_custom_admin_scope(self):
        # Under admin_scope="acme:root", agent_os:admin grants nothing, so it must not
        # turn into every known scope.
        scopes = apply_scope_denies(["agent_os:admin"], ["tasks:delete"], admin_scope="acme:root")
        assert not has_required_scopes(scopes, ["tasks:write"], admin_scope="acme:root")


class TestUnparseableAllows:
    def test_dropped_when_denies_are_present(self):
        # parse_scope reads "agents::run" as a global run grant; the policy parser
        # rejects it, so it cannot be checked against the deny.
        assert apply_scope_denies(["agents::run", "agents:read"], ["agents:run"]) == ["agents:read"]


@pytest.mark.parametrize(
    "scopes,denies,required,resource_id",
    [
        (["agent_os:admin"], ["agents:run"], "agents:run", "x"),
        (["agents:*:run"], ["agents:x:run"], "agents:run", "x"),
        (["agents:run"], ["agents:x:run"], "agents:run", "x"),
        (["agents:x:run"], ["agents:*:run"], "agents:run", "x"),
        (["agent_os:admin", "agents:read"], ["agents:x:read"], "agents:read", "x"),
        (["agent_os:admin"], ["agents:x:delete"], "agents:delete", "x"),
    ],
)
def test_invariant_denied_action_is_never_granted(scopes, denies, required, resource_id):
    effective = apply_scope_denies(scopes, denies)
    assert not has_required_scopes(effective, [required], resource_type="agents", resource_id=resource_id)


def test_custom_admin_scope_that_looks_like_a_resource_scope_is_not_kept():
    # admin_scope="config:read" also appears in the default expansion; keeping it would
    # leave the caller an admin.
    scopes = apply_scope_denies(["config:read"], ["agents:x:run"], admin_scope="config:read")
    assert "config:read" not in scopes
    assert not has_required_scopes(
        scopes, ["agents:run"], resource_type="agents", resource_id="x", admin_scope="config:read"
    )


def test_non_string_allows_are_dropped_instead_of_raising():
    assert apply_scope_denies(["agents:read", 5, {}, None], ["agents:run"]) == ["agents:read"]
