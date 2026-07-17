"""Unit tests for agno.os.scopes — scope parsing, matching, and legacy aliases."""

from agno.os.scopes import (
    LEGACY_RESOURCE_ALIASES,
    check_route_scopes,
    get_accessible_resource_ids,
    get_default_scope_mappings,
    get_resource_context_from_path,
    has_required_scopes,
    parse_scope,
    split_scope,
)


class TestCheckRouteScopes:
    def test_get_listing_allows_through_with_accessible_ids(self):
        # A caller lacking the global scope but holding per-resource scopes gets a
        # filtered listing, not a 403.
        result = check_route_scopes(["agents:a1:read"], get_default_scope_mappings(), "GET", "/agents")
        assert result.allowed is True
        assert result.accessible_resource_ids == {"a1"}

    def test_non_get_idless_route_is_not_allowed_through(self):
        # Regression: the listing allow-through must be GET-only. A create endpoint
        # (POST /agents requires agents:write) must 403, never silently allow through.
        result = check_route_scopes(["agents:a1:read"], get_default_scope_mappings(), "POST", "/agents")
        assert result.allowed is False
        assert result.accessible_resource_ids is None

    def test_caller_with_required_scope_is_allowed(self):
        result = check_route_scopes(["agents:write"], get_default_scope_mappings(), "POST", "/agents")
        assert result.allowed is True

    def test_unmapped_route_allowed(self):
        result = check_route_scopes([], get_default_scope_mappings(), "GET", "/totally/unmapped")
        assert result.allowed is True
        assert result.required_scopes == []


class TestParseScope:
    def test_parses_global_scope(self):
        parsed = parse_scope("agents:read")
        assert parsed.scope_type == "global"
        assert parsed.resource == "agents"
        assert parsed.action == "read"

    def test_parses_per_resource_scope(self):
        parsed = parse_scope("agents:my-agent:run")
        assert parsed.scope_type == "per_resource"
        assert parsed.resource == "agents"
        assert parsed.resource_id == "my-agent"
        assert parsed.action == "run"

    def test_parses_wildcard_resource_scope(self):
        parsed = parse_scope("agents:*:run")
        assert parsed.is_wildcard_resource is True
        assert parsed.resource == "agents"
        assert parsed.action == "run"

    def test_parses_admin_scope(self):
        parsed = parse_scope("agent_os:admin")
        assert parsed.scope_type == "admin"

    def test_legacy_system_scope_aliased_to_config(self):
        parsed = parse_scope("system:read")
        assert parsed.resource == "config"
        assert parsed.action == "read"
        assert parsed.raw == "system:read"

    def test_legacy_per_resource_system_scope_aliased(self):
        parsed = parse_scope("system:some-id:read")
        assert parsed.resource == "config"
        assert parsed.resource_id == "some-id"
        assert parsed.action == "read"

    def test_unknown_scope(self):
        parsed = parse_scope("malformed:scope:with:too:many:parts")
        assert parsed.scope_type == "unknown"


class TestSplitScope:
    """The wire-format split behind the {raw, namespace, sub_namespace, permission} payloads."""

    def test_global_scope(self):
        assert split_scope("agents:read") == ("agents", None, "read")

    def test_per_resource_scope(self):
        assert split_scope("agents:my-agent:run") == ("agents", "my-agent", "run")

    def test_wildcard_scope(self):
        assert split_scope("agents:*:run") == ("agents", "*", "run")

    def test_admin_scope_splits_literally(self):
        # No admin special-casing on the wire: UIs see the literal parts
        assert split_scope("agent_os:admin") == ("agent_os", None, "admin")

    def test_legacy_namespace_renders_under_current_name(self):
        # Wire shape matches enforcement: system:* is enforced as config:* (raw keeps
        # the original string), so API responses never misrepresent the permission.
        assert split_scope("system:read") == ("config", None, "read")
        assert split_scope("system:dep-1:read") == ("config", "dep-1", "read")

    def test_extra_segments_fold_into_sub_namespace(self):
        assert split_scope("agents:a:b:run") == ("agents", "a:b", "run")

    def test_malformed_scope(self):
        assert split_scope("justoneword") == ("justoneword", None, "unknown")


class TestHasRequiredScopes:
    def test_legacy_system_scope_grants_config_access(self):
        """`system:*` tokens keep working where `config:*` is required."""
        assert has_required_scopes(["system:read"], ["config:read"]) is True
        assert has_required_scopes(["system:write"], ["config:write"]) is True

    def test_new_config_scope_works(self):
        assert has_required_scopes(["config:read"], ["config:read"]) is True

    def test_system_scope_does_not_grant_unrelated_access(self):
        """Aliasing system→config must not grant access to unrelated resources."""
        assert has_required_scopes(["system:read"], ["registry:read"]) is False
        assert has_required_scopes(["system:read"], ["agents:read"]) is False

    def test_registry_scope_is_distinct_from_config(self):
        assert has_required_scopes(["config:read"], ["registry:read"]) is False
        assert has_required_scopes(["registry:read"], ["config:read"]) is False

    def test_admin_scope_grants_everything(self):
        assert has_required_scopes(["agent_os:admin"], ["config:read"]) is True
        assert has_required_scopes(["agent_os:admin"], ["registry:read"]) is True

    def test_missing_scope_denied(self):
        assert has_required_scopes([], ["config:read"]) is False
        assert has_required_scopes(["agents:read"], ["config:read"]) is False


class TestLegacyResourceAliases:
    def test_system_is_aliased_to_config(self):
        assert LEGACY_RESOURCE_ALIASES["system"] == "config"

    def test_legacy_system_aliased_in_accessible_ids(self):
        """Per-resource legacy scopes should be aliased for accessible resource lookup too."""
        ids = get_accessible_resource_ids(["system:dep-1:read"], "config")
        assert ids == {"dep-1"}


class TestDefaultScopeMappings:
    def test_config_endpoints_require_config_read(self):
        mappings = get_default_scope_mappings()
        assert mappings["GET /config"] == ["config:read"]
        assert mappings["GET /models"] == ["config:read"]

    def test_database_migrations_require_config_write(self):
        mappings = get_default_scope_mappings()
        assert mappings["POST /databases/*/migrate"] == ["config:write"]
        assert mappings["POST /databases/all/migrate"] == ["config:write"]

    def test_registry_has_its_own_scope(self):
        mappings = get_default_scope_mappings()
        assert mappings["GET /registry"] == ["registry:read"]

    def test_components_endpoints_have_scope_mappings(self):
        mappings = get_default_scope_mappings()
        # Read
        assert mappings["GET /components"] == ["components:read"]
        assert mappings["GET /components/*"] == ["components:read"]
        assert mappings["GET /components/*/configs"] == ["components:read"]
        assert mappings["GET /components/*/configs/*"] == ["components:read"]
        assert mappings["GET /components/*/configs/current"] == ["components:read"]
        # Write
        assert mappings["POST /components"] == ["components:write"]
        assert mappings["PATCH /components/*"] == ["components:write"]
        assert mappings["POST /components/*/configs"] == ["components:write"]
        assert mappings["PATCH /components/*/configs/*"] == ["components:write"]
        assert mappings["POST /components/*/configs/*/set-current"] == ["components:write"]
        # Delete
        assert mappings["DELETE /components/*"] == ["components:delete"]
        assert mappings["DELETE /components/*/configs/*"] == ["components:delete"]

    def test_learnings_endpoints_have_scope_mappings(self):
        mappings = get_default_scope_mappings()
        assert mappings["GET /learnings"] == ["learnings:read"]
        assert mappings["GET /learnings/*"] == ["learnings:read"]
        assert mappings["POST /learnings"] == ["learnings:write"]
        assert mappings["PATCH /learnings/*"] == ["learnings:write"]
        assert mappings["DELETE /learnings/*"] == ["learnings:delete"]


class TestLearningsRouteScopeResolution:
    """The learnings routes must not be left unmapped -- an unmapped route requires no scopes
    and would let any authenticated token bypass RBAC. Verify every route (including the nested
    /learnings/users and /learnings/users/{user_id}) resolves to a learnings scope."""

    def _required(self, method, path):
        from agno.os.middleware.jwt import JWTMiddleware

        mw = JWTMiddleware.__new__(JWTMiddleware)
        mw.scope_mappings = get_default_scope_mappings()
        return mw._get_required_scopes(method, path)

    def test_all_learnings_routes_require_a_learnings_scope(self):
        assert self._required("GET", "/learnings") == ["learnings:read"]
        assert self._required("GET", "/learnings/users") == ["learnings:read"]
        assert self._required("GET", "/learnings/lrn-1") == ["learnings:read"]
        assert self._required("POST", "/learnings") == ["learnings:write"]
        assert self._required("PATCH", "/learnings/lrn-1") == ["learnings:write"]
        assert self._required("DELETE", "/learnings/lrn-1") == ["learnings:delete"]
        # Nested bulk-delete-by-user must also be gated (not left unmapped).
        assert self._required("DELETE", "/learnings/users/priti@agno.com") == ["learnings:delete"]


class TestResourceContextAnchoring:
    """F2: get_resource_context_from_path must anchor to the first path segment, so a
    foreign-family path that merely contains 'agents'/'teams'/'workflows' as a substring
    is never mis-typed and slipped through the GET-listing escape hatch."""

    def test_foreign_family_path_is_not_classified(self):
        assert get_resource_context_from_path("/knowledge/content/agents-onboarding") == (None, None)
        assert get_resource_context_from_path("/traces/agents-run-1") == (None, None)
        assert get_resource_context_from_path("/eval-runs/teams-eval") == (None, None)
        assert get_resource_context_from_path("/agentsfoo") == (None, None)

    def test_real_family_paths_still_classify(self):
        assert get_resource_context_from_path("/agents") == ("agents", None)
        assert get_resource_context_from_path("/agents/a1/runs") == ("agents", "a1")
        assert get_resource_context_from_path("/teams/t1") == ("teams", "t1")
        assert get_resource_context_from_path("/workflows") == ("workflows", None)

    def test_underscoped_get_of_foreign_family_is_denied(self):
        # A caller without knowledge:read requesting a knowledge item whose id contains
        # "agents" must be denied — not waved through the agents listing escape hatch.
        result = check_route_scopes(
            ["sessions:read"], get_default_scope_mappings(), "GET", "/knowledge/content/agents-onboarding"
        )
        assert result.allowed is False
        assert result.accessible_resource_ids is None

    def test_underscoped_get_of_traces_with_agents_substring_is_denied(self):
        result = check_route_scopes(["agents:read"], get_default_scope_mappings(), "GET", "/traces/agents-run-1")
        assert result.allowed is False

    def test_genuine_agents_listing_still_gets_filtered_access(self):
        # The legitimate escape hatch still works for a real /agents listing.
        result = check_route_scopes(["agents:a1:read"], get_default_scope_mappings(), "GET", "/agents")
        assert result.allowed is True
        assert result.accessible_resource_ids == {"a1"}
