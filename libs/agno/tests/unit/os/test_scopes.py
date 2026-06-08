"""Unit tests for agno.os.scopes — scope parsing, matching, and legacy aliases."""

from agno.os.scopes import (
    LEGACY_RESOURCE_ALIASES,
    get_accessible_resource_ids,
    get_default_scope_mappings,
    has_required_scopes,
    parse_scope,
)


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
