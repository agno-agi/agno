"""Unit tests for JWT middleware helper functions."""

import pytest

from agno.os.middleware import JWTMiddleware, TokenSource

# Test JWT secret for middleware initialization
JWT_SECRET = "test-secret-key-for-helper-tests"


class TestGetDefaultExcludedRoutes:
    """Tests for _get_default_excluded_routes helper function."""

    def test_returns_expected_default_routes(self):
        """Test that default excluded routes include standard paths."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

        excluded = middleware._get_default_excluded_routes()

        assert "/" in excluded
        assert "/health" in excluded
        assert "/docs" in excluded
        assert "/redoc" in excluded
        assert "/openapi.json" in excluded
        assert "/docs/oauth2-redirect" in excluded

    def test_returns_list(self):
        """Test that method returns a list."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

        excluded = middleware._get_default_excluded_routes()

        assert isinstance(excluded, list)


class TestExtractResourceIdFromPath:
    """Tests for _extract_resource_id_from_path helper function."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance for testing."""
        return JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

    def test_extracts_agent_id(self, middleware):
        """Test extracting agent ID from path."""
        path = "/agents/my-agent/runs"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result == "my-agent"

    def test_extracts_team_id(self, middleware):
        """Test extracting team ID from path."""
        path = "/teams/my-team/runs"
        result = middleware._extract_resource_id_from_path(path, "teams")
        assert result == "my-team"

    def test_extracts_workflow_id(self, middleware):
        """Test extracting workflow ID from path."""
        path = "/workflows/my-workflow/runs"
        result = middleware._extract_resource_id_from_path(path, "workflows")
        assert result == "my-workflow"

    def test_extracts_id_with_dashes(self, middleware):
        """Test extracting ID with dashes."""
        path = "/agents/my-complex-agent-id/runs"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result == "my-complex-agent-id"

    def test_extracts_id_with_underscores(self, middleware):
        """Test extracting ID with underscores."""
        path = "/agents/my_agent_id/runs"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result == "my_agent_id"

    def test_extracts_id_with_numbers(self, middleware):
        """Test extracting ID with numbers."""
        path = "/agents/agent123/runs"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result == "agent123"

    def test_returns_none_for_list_endpoint(self, middleware):
        """Test that listing endpoint returns None."""
        path = "/agents"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result is None

    def test_returns_none_for_wrong_resource_type(self, middleware):
        """Test that wrong resource type returns None."""
        path = "/agents/my-agent/runs"
        result = middleware._extract_resource_id_from_path(path, "teams")
        assert result is None

    def test_extracts_id_from_simple_path(self, middleware):
        """Test extracting ID from simple resource path."""
        path = "/agents/test-agent"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result == "test-agent"

    def test_handles_uuid_style_id(self, middleware):
        """Test extracting UUID-style ID."""
        path = "/agents/550e8400-e29b-41d4-a716-446655440000/runs"
        result = middleware._extract_resource_id_from_path(path, "agents")
        assert result == "550e8400-e29b-41d4-a716-446655440000"


class TestIsRouteExcluded:
    """Tests for _is_route_excluded helper function."""

    def test_excludes_default_routes(self):
        """Test that default routes are excluded."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

        assert middleware._is_route_excluded("/health") is True
        assert middleware._is_route_excluded("/docs") is True
        assert middleware._is_route_excluded("/redoc") is True
        assert middleware._is_route_excluded("/openapi.json") is True
        assert middleware._is_route_excluded("/") is True

    def test_does_not_exclude_protected_routes(self):
        """Test that protected routes are not excluded."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

        assert middleware._is_route_excluded("/agents") is False
        assert middleware._is_route_excluded("/teams") is False
        assert middleware._is_route_excluded("/workflows") is False
        assert middleware._is_route_excluded("/sessions") is False

    def test_custom_excluded_routes(self):
        """Test with custom excluded routes."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            excluded_route_paths=["/custom", "/public/*"],
        )

        assert middleware._is_route_excluded("/custom") is True
        assert middleware._is_route_excluded("/public/data") is True
        assert middleware._is_route_excluded("/protected") is False

    def test_wildcard_pattern_matching(self):
        """Test wildcard pattern matching."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            excluded_route_paths=["/api/public/*"],
        )

        assert middleware._is_route_excluded("/api/public/status") is True
        assert middleware._is_route_excluded("/api/public/health") is True
        assert middleware._is_route_excluded("/api/private/data") is False

    def test_handles_trailing_slash(self):
        """Test that trailing slashes are handled."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            excluded_route_paths=["/health"],
        )

        assert middleware._is_route_excluded("/health/") is True
        assert middleware._is_route_excluded("/health") is True

    def test_empty_excluded_routes(self):
        """Test with empty excluded routes list."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            excluded_route_paths=[],
        )

        assert middleware._is_route_excluded("/health") is False
        assert middleware._is_route_excluded("/anything") is False


class TestGetRequiredScopes:
    """Tests for _get_required_scopes helper function."""

    @pytest.fixture
    def middleware_with_auth(self):
        """Create middleware instance with authorization enabled."""
        return JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            authorization=True,
        )

    def test_returns_scopes_for_agents_list(self, middleware_with_auth):
        """Test scopes for listing agents."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/agents")
        assert "agents:read" in scopes

    def test_returns_scopes_for_agent_run(self, middleware_with_auth):
        """Test scopes for running an agent."""
        scopes = middleware_with_auth._get_required_scopes("POST", "/agents/my-agent/runs")
        assert "agents:run" in scopes

    def test_returns_scopes_for_teams_list(self, middleware_with_auth):
        """Test scopes for listing teams."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/teams")
        assert "teams:read" in scopes

    def test_returns_scopes_for_team_run(self, middleware_with_auth):
        """Test scopes for running a team."""
        scopes = middleware_with_auth._get_required_scopes("POST", "/teams/my-team/runs")
        assert "teams:run" in scopes

    def test_returns_scopes_for_workflows_list(self, middleware_with_auth):
        """Test scopes for listing workflows."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/workflows")
        assert "workflows:read" in scopes

    def test_returns_scopes_for_workflow_run(self, middleware_with_auth):
        """Test scopes for running a workflow."""
        scopes = middleware_with_auth._get_required_scopes("POST", "/workflows/my-workflow/runs")
        assert "workflows:run" in scopes

    def test_returns_scopes_for_sessions(self, middleware_with_auth):
        """Test scopes for sessions endpoint."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/sessions")
        assert "sessions:read" in scopes

    def test_returns_scopes_for_config(self, middleware_with_auth):
        """Test scopes for config endpoint."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/config")
        assert "system:read" in scopes

    def test_returns_scopes_for_traces(self, middleware_with_auth):
        """Test scopes for traces endpoint."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/traces")
        assert "traces:read" in scopes

    def test_returns_scopes_for_trace_detail(self, middleware_with_auth):
        """Test scopes for trace detail endpoint."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/traces/trace-123")
        assert "traces:read" in scopes

    def test_returns_scopes_for_trace_session_stats(self, middleware_with_auth):
        """Test scopes for trace session stats endpoint."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/trace_session_stats")
        assert "traces:read" in scopes

    def test_returns_empty_for_unknown_route(self, middleware_with_auth):
        """Test that unknown routes return empty scopes."""
        scopes = middleware_with_auth._get_required_scopes("GET", "/unknown/route")
        assert scopes == []

    def test_custom_scope_mappings(self):
        """Test with custom scope mappings."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            authorization=True,
            scope_mappings={
                "GET /custom/endpoint": ["custom:read"],
                "POST /custom/action": ["custom:write"],
            },
        )

        scopes = middleware._get_required_scopes("GET", "/custom/endpoint")
        assert "custom:read" in scopes

        scopes = middleware._get_required_scopes("POST", "/custom/action")
        assert "custom:write" in scopes

    def test_empty_scopes_for_explicitly_allowed_route(self):
        """Test that explicitly allowed routes return empty scopes."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            authorization=True,
            scope_mappings={
                "GET /public/data": [],  # Explicitly allow without scopes
            },
        )

        scopes = middleware._get_required_scopes("GET", "/public/data")
        assert scopes == []


class TestGetMissingTokenErrorMessage:
    """Tests for _get_missing_token_error_message helper function."""

    def test_header_source_message(self):
        """Test error message for header token source."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            token_source=TokenSource.HEADER,
        )

        message = middleware._get_missing_token_error_message()
        assert "Authorization header missing" in message

    def test_cookie_source_message(self):
        """Test error message for cookie token source."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            token_source=TokenSource.COOKIE,
            cookie_name="my_token",
        )

        message = middleware._get_missing_token_error_message()
        assert "my_token" in message
        assert "cookie" in message.lower()

    def test_both_source_message(self):
        """Test error message for both token sources."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            token_source=TokenSource.BOTH,
            cookie_name="jwt_cookie",
        )

        message = middleware._get_missing_token_error_message()
        assert "jwt_cookie" in message
        assert "header" in message.lower()
        assert "cookie" in message.lower()

    def test_custom_cookie_name_in_message(self):
        """Test that custom cookie name appears in error message."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            token_source=TokenSource.COOKIE,
            cookie_name="custom_auth_token",
        )

        message = middleware._get_missing_token_error_message()
        assert "custom_auth_token" in message


class TestIsOriginAllowed:
    """Tests for _is_origin_allowed helper function."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance for testing."""
        return JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

    def test_allows_all_when_no_origins_configured(self, middleware):
        """Test that all origins are allowed when cors_allowed_origins is None."""
        assert middleware._is_origin_allowed("http://localhost:3000", None) is True
        assert middleware._is_origin_allowed("https://example.com", None) is True

    def test_allows_all_when_empty_origins_list(self, middleware):
        """Test that all origins are allowed when cors_allowed_origins is empty."""
        assert middleware._is_origin_allowed("http://localhost:3000", []) is True
        assert middleware._is_origin_allowed("https://example.com", []) is True

    def test_allows_configured_origin(self, middleware):
        """Test that configured origins are allowed."""
        allowed_origins = ["http://localhost:3000", "https://example.com"]

        assert middleware._is_origin_allowed("http://localhost:3000", allowed_origins) is True
        assert middleware._is_origin_allowed("https://example.com", allowed_origins) is True

    def test_denies_unconfigured_origin(self, middleware):
        """Test that unconfigured origins are denied."""
        allowed_origins = ["http://localhost:3000"]

        assert middleware._is_origin_allowed("https://example.com", allowed_origins) is False
        assert middleware._is_origin_allowed("http://malicious.com", allowed_origins) is False

    def test_case_sensitive_origin_matching(self, middleware):
        """Test that origin matching is case sensitive."""
        allowed_origins = ["http://localhost:3000"]

        assert middleware._is_origin_allowed("http://localhost:3000", allowed_origins) is True
        assert middleware._is_origin_allowed("HTTP://LOCALHOST:3000", allowed_origins) is False


class TestMiddlewareInitialization:
    """Tests for JWTMiddleware initialization."""

    def test_raises_error_without_verification_key(self):
        """Test that middleware raises error when no verification key provided."""
        with pytest.raises(ValueError) as exc_info:
            JWTMiddleware(
                app=None,
                verification_key=None,
                algorithm="HS256",
            )

        assert "verification key is required" in str(exc_info.value).lower()

    def test_authorization_enabled_implicitly_with_scope_mappings(self):
        """Test that authorization is enabled when scope_mappings provided."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            scope_mappings={"GET /test": ["test:read"]},
        )

        assert middleware.authorization is True

    def test_authorization_stays_false_when_explicit(self):
        """Test that authorization=False is respected even with scope_mappings."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            authorization=False,
            scope_mappings={"GET /test": ["test:read"]},
        )

        assert middleware.authorization is False

    def test_default_scope_mappings_merged_with_custom(self):
        """Test that custom scope mappings are merged with defaults."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            authorization=True,
            scope_mappings={"GET /custom": ["custom:read"]},
        )

        # Should have both default and custom mappings
        assert "GET /agents" in middleware.scope_mappings
        assert "GET /custom" in middleware.scope_mappings
        assert middleware.scope_mappings["GET /custom"] == ["custom:read"]

    def test_custom_scope_mappings_override_defaults(self):
        """Test that custom scope mappings can override defaults."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            authorization=True,
            scope_mappings={"GET /agents": ["custom:agents:read"]},
        )

        assert middleware.scope_mappings["GET /agents"] == ["custom:agents:read"]

    def test_custom_admin_scope(self):
        """Test that custom admin scope is used."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            admin_scope="custom:admin",
        )

        assert middleware.admin_scope == "custom:admin"

    def test_default_admin_scope(self):
        """Test that default admin scope is used when not specified."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
        )

        assert middleware.admin_scope == "agent_os:admin"

    def test_custom_claims_configuration(self):
        """Test custom claims configuration."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            user_id_claim="custom_user",
            session_id_claim="custom_session",
            scopes_claim="custom_scopes",
            audience_claim="custom_aud",
        )

        assert middleware.user_id_claim == "custom_user"
        assert middleware.session_id_claim == "custom_session"
        assert middleware.scopes_claim == "custom_scopes"
        assert middleware.audience_claim == "custom_aud"

    def test_dependencies_and_session_state_claims(self):
        """Test dependencies and session state claims configuration."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            dependencies_claims=["org_id", "tenant_id"],
            session_state_claims=["theme", "language"],
        )

        assert middleware.dependencies_claims == ["org_id", "tenant_id"]
        assert middleware.session_state_claims == ["theme", "language"]

    def test_token_source_configuration(self):
        """Test token source configuration."""
        middleware = JWTMiddleware(
            app=None,
            verification_key=JWT_SECRET,
            algorithm="HS256",
            token_source=TokenSource.COOKIE,
            cookie_name="my_jwt",
        )

        assert middleware.token_source == TokenSource.COOKIE
        assert middleware.cookie_name == "my_jwt"
