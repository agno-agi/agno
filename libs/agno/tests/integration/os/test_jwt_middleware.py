"""Integration tests for JWT middleware functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, TokenSource

# Test JWT secret
JWT_SECRET = "test-secret-key-for-integration-tests"


@pytest.fixture
def jwt_token():
    """Create a test JWT token with known claims."""
    payload = {
        "sub": "test_user_123",  # Will be extracted as user_id
        "session_id": "test_session_456",  # Will be extracted as session_id
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
        # Dependency claims
        "name": "John Doe",
        "email": "john@example.com",
        "roles": ["admin", "user"],
        "org_id": "test_org_789",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def jwt_test_agent():
    """Create a test agent with a tool that accesses JWT data from request state."""

    agent = Agent(
        name="jwt-test-agent",
        db=InMemoryDb(),
        instructions="You are a test agent that can access JWT information and user profiles.",
    )
    # Override deep_copy to return the same instance for testing
    # This is needed because AgentOS uses create_fresh=True which calls deep_copy,
    # and our mocks need to be on the same instance that gets used
    agent.deep_copy = lambda **kwargs: agent
    return agent


@pytest.fixture
def jwt_test_client(jwt_test_agent):
    """Create a test client with JWT middleware configured."""
    # Create AgentOS with the JWT test agent
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    # Add JWT middleware
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",  # Extract user_id from 'sub' claim
        session_id_claim="session_id",  # Extract session_id from 'session_id' claim
        dependencies_claims=["name", "email", "roles", "org_id"],  # Extract these as dependencies
        validate=True,  # Enable token validation for this test
        authorization=False,  # Disable authorization checks for this test
    )

    return TestClient(app)


def test_extracts_claims_correctly(jwt_test_client, jwt_token, jwt_test_agent):
    """Test that JWT middleware correctly extracts claims and makes them available to tools."""

    # Mock the agent's arun method to capture the tool call results
    mock_run_output = type(
        "MockRunOutput",
        (),
        {"to_dict": lambda self: {"content": "JWT information retrieved successfully", "run_id": "test_run_123"}},
    )()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Make request with JWT token
        response = jwt_test_client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {jwt_token}"},
            data={
                "message": "Get my JWT info",
                "stream": "false",
            },
        )

        assert response.status_code == 200

        # Verify the agent was called with the request that has JWT data
        mock_arun.assert_called_once()
        call_args = mock_arun.call_args

        # The agent should have been called - we can't directly inspect the request state
        # but we can verify the call was made successfully with JWT authentication
        assert call_args is not None
        assert "input" in call_args.kwargs
        assert call_args.kwargs["input"] == "Get my JWT info"
        assert call_args.kwargs["user_id"] == "test_user_123"
        assert call_args.kwargs["session_id"] == "test_session_456"
        assert call_args.kwargs["dependencies"] == {
            "name": "John Doe",
            "email": "john@example.com",
            "roles": ["admin", "user"],
            "org_id": "test_org_789",
        }


def test_without_token_fails_validation(jwt_test_client):
    """Test that requests without JWT token are rejected when validation is enabled."""

    response = jwt_test_client.post(
        "/agents/jwt-test-agent/runs",
        data={
            "message": "This should fail",
            "stream": "false",
        },
    )

    # Should return 401 Unauthorized due to missing token
    assert response.status_code == 401
    assert "Authorization header missing" in response.json()["detail"]


def test_with_invalid_token_fails(jwt_test_client):
    """Test that requests with invalid JWT token are rejected."""

    response = jwt_test_client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": "Bearer invalid.token.here"},
        data={
            "message": "This should fail",
            "stream": "false",
        },
    )

    # Should return 401 Unauthorized due to invalid token
    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]


def test_with_expired_token_fails(jwt_test_client):
    """Test that requests with expired JWT token are rejected."""

    # Create expired token
    expired_payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) - timedelta(hours=1),  # Expired 1 hour ago
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    expired_token = jwt.encode(expired_payload, JWT_SECRET, algorithm="HS256")

    response = jwt_test_client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {expired_token}"},
        data={
            "message": "This should fail",
            "stream": "false",
        },
    )

    # Should return 401 Unauthorized due to expired token
    assert response.status_code == 401
    assert "Token has expired" in response.json()["detail"]


def test_validation_disabled(jwt_test_agent):
    """Test JWT middleware with signature validation disabled still requires token."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        validate=False,
    )

    client = TestClient(app)

    # Request without token should still fail - token is always required
    response = client.get("/agents")
    assert response.status_code == 401
    assert "Authorization header missing" in response.json()["detail"]

    # Request with token (any signature) should work since validate=False
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:read"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jwt.encode(payload, "any-secret-doesnt-matter", algorithm="HS256")

    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_custom_claims_configuration(jwt_test_agent):
    """Test JWT middleware with custom claim configurations."""

    # Create AgentOS with custom claim mappings
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_header_key="Authorization",
        user_id_claim="custom_user_id",  # Different claim name
        session_id_claim="custom_session",  # Different claim name
        dependencies_claims=["department", "level"],  # Different dependency claims
        validate=True,
    )

    client = TestClient(app)

    # Create token with custom claims
    custom_payload = {
        "custom_user_id": "custom_user_456",
        "custom_session": "custom_session_789",
        "department": "Engineering",
        "level": "Senior",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    custom_token = jwt.encode(custom_payload, JWT_SECRET, algorithm="HS256")

    # Mock the agent's arun method
    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Custom claims processed"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {custom_token}"},
            data={
                "message": "Test custom claims",
                "stream": "false",
            },
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_excluded_routes(jwt_test_agent):
    """Test that JWT middleware can exclude certain routes from authentication."""

    # Create AgentOS
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    # Add JWT middleware with excluded routes
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_header_key="Authorization",
        user_id_claim="sub",
        session_id_claim="session_id",
        dependencies_claims=["name", "email"],
        validate=True,
        excluded_route_paths=[
            "/health",  # Exclude health endpoint
            "/sessions",  # Exclude sessions endpoint
            "/sessions/*",  # Exclude sessions endpoint with wildcard
        ],
    )

    client = TestClient(app)

    # Health endpoint should work without token (excluded)
    response = client.get("/health")
    assert response.status_code == 200

    # Sessions endpoint should work without token (excluded)
    response = client.get("/sessions")
    assert response.status_code == 200

    # Sessions endpoint should work without token (excluded)
    response = client.get("/sessions/123")
    assert response.status_code != 401

    # Agent endpoint should require token (not excluded)
    response = client.post(
        "/agents/jwt-test-agent/runs",
        data={"message": "This should fail", "stream": "false"},
    )
    assert response.status_code == 401


def test_cookie_token_source(jwt_test_agent, jwt_token):
    """Test JWT middleware with cookie as token source."""

    # Create AgentOS with cookie-based JWT middleware
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_source=TokenSource.COOKIE,
        cookie_name="jwt_token",
        user_id_claim="sub",
        session_id_claim="session_id",
        dependencies_claims=["name", "email", "roles", "org_id"],
        validate=True,
    )

    client = TestClient(app)

    # Mock the agent's arun method
    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Cookie auth successful"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Request with JWT in cookie should succeed
        client.cookies.set("jwt_token", jwt_token)
        response = client.post(
            "/agents/jwt-test-agent/runs",
            data={
                "message": "Test cookie auth",
                "stream": "false",
            },
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()

        # Verify JWT claims are passed to agent
        call_args = mock_arun.call_args
        assert call_args.kwargs["user_id"] == "test_user_123"
        assert call_args.kwargs["session_id"] == "test_session_456"


def test_cookie_missing_token_fails(jwt_test_agent):
    """Test that cookie-based middleware fails when cookie is missing."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_source=TokenSource.COOKIE,
        cookie_name="jwt_token",
        validate=True,
    )

    client = TestClient(app)

    # Request without cookie should fail
    response = client.post(
        "/agents/jwt-test-agent/runs",
        data={"message": "This should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "JWT cookie 'jwt_token' missing" in response.json()["detail"]


def test_both_token_sources_header_first(jwt_test_agent, jwt_token):
    """Test JWT middleware with both token sources, header takes precedence."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_source=TokenSource.BOTH,
        cookie_name="jwt_cookie",
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create different token for cookie to verify header is used
    cookie_payload = {
        "sub": "cookie_user_456",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    cookie_token = jwt.encode(cookie_payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Both sources test"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Set both header and cookie - header should take precedence
        client.cookies.set("jwt_cookie", cookie_token)
        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {jwt_token}"},
            data={"message": "Test both sources", "stream": "false"},
        )

        assert response.status_code == 200
        call_args = mock_arun.call_args

        # Should use header token (test_user_123), not cookie token (cookie_user_456)
        assert call_args.kwargs["user_id"] == "test_user_123"


def test_both_token_sources_cookie_fallback(jwt_test_agent, jwt_token):
    """Test JWT middleware with both token sources, falls back to cookie."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_source=TokenSource.BOTH,
        cookie_name="jwt_cookie",
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Cookie fallback test"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Only set cookie, no header - should fall back to cookie
        client.cookies.set("jwt_cookie", jwt_token)
        response = client.post(
            "/agents/jwt-test-agent/runs",
            data={"message": "Test cookie fallback", "stream": "false"},
        )

        assert response.status_code == 200
        call_args = mock_arun.call_args
        assert call_args.kwargs["user_id"] == "test_user_123"


def test_both_token_sources_missing_both_fails(jwt_test_agent):
    """Test that both token sources fail when neither header nor cookie present."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        token_source=TokenSource.BOTH,
        cookie_name="jwt_cookie",
        validate=True,
    )

    client = TestClient(app)

    # Request with neither header nor cookie should fail
    response = client.post(
        "/agents/jwt-test-agent/runs",
        data={"message": "This should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "JWT token missing from both Authorization header and 'jwt_cookie' cookie" in response.json()["detail"]


def test_custom_cookie_name(jwt_test_agent, jwt_token):
    """Test JWT middleware with custom cookie name."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    custom_cookie_name = "custom_auth_token"
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_source=TokenSource.COOKIE,
        cookie_name=custom_cookie_name,
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Custom cookie name test"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Set JWT in custom-named cookie
        client.cookies.set(custom_cookie_name, jwt_token)
        response = client.post(
            "/agents/jwt-test-agent/runs",
            data={"message": "Test custom cookie name", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()

        call_args = mock_arun.call_args
        assert call_args.kwargs["user_id"] == "test_user_123"


def test_cookie_invalid_token_fails(jwt_test_agent):
    """Test that cookie-based middleware fails with invalid token."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_source=TokenSource.COOKIE,
        cookie_name="jwt_token",
        validate=True,
    )

    client = TestClient(app)

    # Set invalid token in cookie
    client.cookies.set("jwt_token", "invalid.jwt.token")
    response = client.post(
        "/agents/jwt-test-agent/runs",
        data={"message": "This should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]


def test_scopes_string_format(jwt_test_agent):
    """Test JWT middleware with scopes claim as space-separated string."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        scopes_claim="scope",  # Standard OAuth2 scope claim
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create token with string scopes
    payload = {
        "sub": "test_user_123",
        "scope": "read write admin",  # Space-separated string
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Scopes extracted"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test string scopes", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_scopes_list_format(jwt_test_agent):
    """Test JWT middleware with scopes claim as list."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        scopes_claim="permissions",  # Custom scope claim name
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create token with list scopes
    payload = {
        "sub": "test_user_123",
        "permissions": ["read", "write", "admin"],  # List format
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "List scopes extracted"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test list scopes", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_no_scopes_claim(jwt_test_agent):
    """Test JWT middleware when no scopes claim is configured."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        scopes_claim=None,  # No scopes extraction
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create token with scopes that should be ignored
    payload = {
        "sub": "test_user_123",
        "scope": "read write admin",  # This should be ignored
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "No scopes configured"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test no scopes", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_session_state_claims(jwt_test_agent):
    """Test JWT middleware with session_state_claims extraction."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        session_state_claims=["session_data", "user_preferences", "theme"],
        validate=True,
    )

    client = TestClient(app)

    # Create token with session state claims
    payload = {
        "sub": "test_user_123",
        "session_data": {"last_login": "2023-10-01T10:00:00Z"},
        "user_preferences": {"language": "en", "timezone": "UTC"},
        "theme": "dark",
        "other_claim": "should_be_ignored",  # Not in session_state_claims
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Session state extracted"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test session state", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_custom_token_header_key(jwt_test_agent):
    """Test JWT middleware with custom token header key instead of Authorization."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    custom_header_key = "X-Auth-Token"
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        token_header_key=custom_header_key,
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create valid token
    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Custom header success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Test with custom header
        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={custom_header_key: f"Bearer {token}"},
            data={"message": "Test custom header", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()

        # Test that Authorization header is ignored when custom header is configured
        mock_arun.reset_mock()
        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},  # Should be ignored
            data={"message": "Should fail", "stream": "false"},
        )

        assert response.status_code == 401  # Should fail because custom header key is missing


def test_malformed_authorization_header(jwt_test_agent):
    """Test JWT middleware with malformed Authorization headers."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create valid token for testing
    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Test malformed header without space
    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer{token}"},  # No space between Bearer and token
        data={"message": "Test malformed header", "stream": "false"},
    )
    assert response.status_code == 401

    # Test header with just "Bearer" and no token
    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": "Bearer"},
        data={"message": "Test bearer only", "stream": "false"},
    )
    assert response.status_code == 401


def test_missing_session_id_claim(jwt_test_agent):
    """Test JWT middleware when session_id_claim doesn't exist in token."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        session_id_claim="missing_session_claim",  # Claim that won't exist
        validate=True,
    )

    client = TestClient(app)

    # Create token without the expected session_id_claim
    payload = {
        "sub": "test_user_123",
        "session_id": "test_session_456",  # Different from configured session_id_claim
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type(
        "MockRunOutput", (), {"to_dict": lambda self: {"content": "Missing session claim handled"}}
    )()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test missing session claim", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()

        # Should still be called, but without session_id
        call_args = mock_arun.call_args
        assert call_args.kwargs.get("user_id") == "test_user_123"
        assert call_args.kwargs.get("session_id") != "test_session_456"


def test_general_exception_during_decode(jwt_test_agent):
    """Test JWT middleware handles general exceptions during token decode."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Patch jwt.decode to raise a general exception
    with patch("jwt.decode", side_effect=Exception("General decode error")):
        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": "Bearer some.valid.format"},
            data={"message": "Test general exception", "stream": "false"},
        )

        assert response.status_code == 401
        assert "Error decoding token: General decode error" in response.json()["detail"]


def test_different_algorithm_rs256(jwt_test_agent):
    """Test JWT middleware with RS256 algorithm."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Generate RSA key pair for testing
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[public_pem.decode("utf-8")],  # Use public key for verification
        algorithm="RS256",
        user_id_claim="sub",
        validate=True,
    )

    client = TestClient(app)

    # Create RS256 token
    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "RS256 success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test RS256", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_request_state_token_storage(jwt_test_agent):
    """Test that JWT middleware stores token and authentication status in request.state."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    # We'll need to create a custom endpoint to inspect request.state
    @app.get("/test-request-state")
    async def test_endpoint(request: Request):
        return {
            "has_token": hasattr(request.state, "token"),
            "has_authenticated": hasattr(request.state, "authenticated"),
            "authenticated": getattr(request.state, "authenticated", None),
            "token_present": hasattr(request.state, "token") and getattr(request.state, "token") is not None,
        }

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=False,  # Don't fail on validation errors, just set authenticated=False
    )

    client = TestClient(app)

    # Test with valid token
    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    valid_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.get("/test-request-state", headers={"Authorization": f"Bearer {valid_token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["has_token"] is True
    assert data["has_authenticated"] is True
    assert data["authenticated"] is True
    assert data["token_present"] is True

    # Test with invalid token (should still store token but mark as not authenticated)
    response = client.get("/test-request-state", headers={"Authorization": "Bearer invalid.token.here"})

    assert response.status_code == 200
    data = response.json()
    assert data["has_token"] is True
    assert data["has_authenticated"] is True
    assert data["authenticated"] is False
    assert data["token_present"] is True


# --- Authorization Tests ---


def test_authorization_enabled_flag_set_true(jwt_test_agent):
    """Test that authorization_enabled is set to True in request.state when authorization=True."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    @app.get("/test-authorization-flag")
    async def test_endpoint(request: Request):
        return {
            "authorization_enabled": getattr(request.state, "authorization_enabled", None),
        }

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        authorization=True,
        scope_mappings={
            "GET /test-authorization-flag": [],  # Allow access without scopes
        },
    )

    client = TestClient(app)

    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:read"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.get("/test-authorization-flag", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["authorization_enabled"] is True


def test_authorization_enabled_flag_set_false(jwt_test_agent):
    """Test that authorization_enabled is set to False in request.state when authorization=False."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    @app.get("/test-authorization-flag")
    async def test_endpoint(request: Request):
        return {
            "authorization_enabled": getattr(request.state, "authorization_enabled", None),
        }

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        authorization=False,  # Explicitly disable authorization
    )

    client = TestClient(app)

    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.get("/test-authorization-flag", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["authorization_enabled"] is False


def test_authorization_enabled_implicitly_by_scope_mappings(jwt_test_agent):
    """Test that authorization is implicitly enabled when scope_mappings are provided."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    @app.get("/test-authorization-flag")
    async def test_endpoint(request: Request):
        return {
            "authorization_enabled": getattr(request.state, "authorization_enabled", None),
        }

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        # authorization not explicitly set, but scope_mappings provided
        scope_mappings={
            "GET /test-authorization-flag": [],  # Allow access without scopes
        },
    )

    client = TestClient(app)

    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.get("/test-authorization-flag", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["authorization_enabled"] is True


def test_router_checks_skipped_when_authorization_disabled(jwt_test_agent):
    """Test that router-level authorization checks are skipped when authorization=False."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        authorization=False,  # Authorization disabled
    )

    client = TestClient(app)

    # Create token WITHOUT any scopes - should still be able to access agents
    payload = {
        "sub": "test_user_123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
        # No scopes claim
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Should be able to list agents without scopes when authorization is disabled
    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})

    # Should succeed (200) because authorization checks are skipped
    assert response.status_code == 200


def test_router_checks_enforced_when_authorization_enabled(jwt_test_agent):
    """Test that router-level authorization checks are enforced when authorization=True."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,  # Authorization enabled
    )

    client = TestClient(app)

    # Create token WITHOUT any scopes
    payload_no_scopes = {
        "sub": "test_user_123",
        "scopes": [],  # Empty scopes
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token_no_scopes = jwt.encode(payload_no_scopes, JWT_SECRET, algorithm="HS256")

    # Should fail to list agents without proper scopes when authorization is enabled
    response = client.get("/agents", headers={"Authorization": f"Bearer {token_no_scopes}"})

    # Should fail (403) because user has no agent scopes
    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]


def test_router_allows_access_with_valid_scopes(jwt_test_agent):
    """Test that router-level checks allow access with valid scopes."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with agents:read scope
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:read"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Should be able to list agents with agents:read scope
    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_router_allows_specific_agent_access(jwt_test_agent):
    """Test that router-level checks allow access to specific agent with proper scopes."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with specific agent scope
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:jwt-test-agent:read"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Should be able to access the specific agent
    response = client.get("/agents/jwt-test-agent", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_router_denies_wrong_agent_access(jwt_test_agent):
    """Test that router-level checks deny access to agent user doesn't have scope for."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with scope for different agent
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:other-agent:read"],  # Scope for different agent
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Should be denied access to jwt-test-agent
    response = client.get("/agents/jwt-test-agent", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]


def test_router_run_agent_with_valid_scope(jwt_test_agent):
    """Test that agent run endpoint works with proper run scope."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with agent run scope
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:jwt-test-agent:run"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Success with run scope"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test with run scope", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_router_denies_run_without_scope(jwt_test_agent):
    """Test that agent run endpoint is denied without run scope."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with only read scope (no run scope)
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:jwt-test-agent:read"],  # Only read, not run
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]


def test_admin_scope_grants_all_access(jwt_test_agent):
    """Test that admin scope grants access to all resources."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with admin scope
    payload = {
        "sub": "admin_user",
        "scopes": ["agent_os:admin"],  # Admin scope
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Should be able to list agents
    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    # Should be able to access specific agent
    response = client.get("/agents/jwt-test-agent", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    # Should be able to run agent
    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Admin success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Admin test", "stream": "false"},
        )

        assert response.status_code == 200


def test_wildcard_scope_grants_resource_access(jwt_test_agent):
    """Test that wildcard scope grants access to all resources of that type."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        scopes_claim="scopes",
        validate=True,
        authorization=True,
    )

    client = TestClient(app)

    # Create token with wildcard agent scope
    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:*:read", "agents:*:run"],  # Wildcard for all agents
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Should be able to list agents
    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    # Should be able to access any agent
    response = client.get("/agents/jwt-test-agent", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    # Should be able to run any agent
    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Wildcard success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Wildcard test", "stream": "false"},
        )

        assert response.status_code == 200


def test_validate_false_extracts_scopes(jwt_test_agent):
    """Test that validate=False still extracts scopes from token."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    @app.get("/test-scopes")
    async def test_endpoint(request: Request):
        return {
            "authenticated": getattr(request.state, "authenticated", None),
            "scopes": getattr(request.state, "scopes", None),
            "user_id": getattr(request.state, "user_id", None),
        }

    app.add_middleware(
        JWTMiddleware,
        validate=False,
        user_id_claim="sub",
        scope_mappings={
            "GET /test-scopes": [],
        },
    )

    client = TestClient(app)

    payload = {
        "sub": "test_user_123",
        "scopes": ["agents:read", "agents:run"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, "any-secret", algorithm="HS256")

    response = client.get("/test-scopes", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["scopes"] == ["agents:read", "agents:run"]
    assert data["user_id"] == "test_user_123"


def test_validate_false_with_authorization_checks_scopes(jwt_test_agent):
    """Test that validate=False with authorization=True still enforces scopes."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        validate=False,
        authorization=True,
    )

    client = TestClient(app)

    # Token with no scopes should get 403
    payload = {
        "sub": "test_user_123",
        "scopes": [],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, "any-secret", algorithm="HS256")

    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]

    # Token with correct scopes should succeed
    payload["scopes"] = ["agents:read"]
    token = jwt.encode(payload, "any-secret", algorithm="HS256")

    response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


# --- Audience Verification Tests ---
def test_audience_verification_with_explicit_audience_success(jwt_test_agent):
    """Test that tokens with matching explicit audience are accepted when verify_audience=True."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience="test-audience-123",  # Explicit audience
    )

    client = TestClient(app)

    # Create token with matching audience
    payload = {
        "sub": "test_user_123",
        "aud": "test-audience-123",  # Matches explicit audience
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Audience match success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test audience match", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_audience_verification_with_explicit_audience_failure(jwt_test_agent):
    """Test that tokens with non-matching explicit audience are rejected when verify_audience=True."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience="test-audience-123",  # Explicit audience
    )

    client = TestClient(app)

    # Create token with non-matching audience
    payload = {
        "sub": "test_user_123",
        "aud": "wrong-audience-456",  # Doesn't match explicit audience
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "Invalid token audience" in response.json()["detail"]


def test_audience_verification_with_agent_os_id(jwt_test_agent):
    """Test that tokens with matching agent_os_id are accepted when verify_audience=True without explicit audience."""

    agent_os_id = "test-agent-os-789"
    agent_os = AgentOS(id=agent_os_id, agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        # No explicit audience - should use agent_os_id
    )

    client = TestClient(app)

    # Create token with matching agent_os_id as audience
    payload = {
        "sub": "test_user_123",
        "aud": agent_os_id,  # Matches agent_os_id
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "AgentOS ID match success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test agent_os_id match", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_audience_verification_with_agent_os_id_failure(jwt_test_agent):
    """Test that tokens with non-matching agent_os_id are rejected when verify_audience=True without explicit audience."""

    agent_os_id = "test-agent-os-789"
    agent_os = AgentOS(id=agent_os_id, agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        # No explicit audience - should use agent_os_id
    )

    client = TestClient(app)

    # Create token with non-matching audience
    payload = {
        "sub": "test_user_123",
        "aud": "wrong-agent-os-id",  # Doesn't match agent_os_id
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "Invalid token audience" in response.json()["detail"]


def test_audience_verification_disabled(jwt_test_agent):
    """Test that audience is not checked when verify_audience=False."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=False,  # Audience verification disabled
        audience="test-audience-123",
    )

    client = TestClient(app)

    # Create token with non-matching audience (should still work since verify_audience=False)
    payload = {
        "sub": "test_user_123",
        "aud": "wrong-audience-456",  # Doesn't match, but should be ignored
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Audience ignored"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test audience ignored", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_audience_verification_with_custom_audience_claim(jwt_test_agent):
    """Test that custom audience claim name works correctly."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience="test-audience-123",
        audience_claim="custom_aud",  # Custom audience claim name
    )

    client = TestClient(app)

    # Create token with custom audience claim name
    payload = {
        "sub": "test_user_123",
        "custom_aud": "test-audience-123",  # Using custom claim name
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type(
        "MockRunOutput", (), {"to_dict": lambda self: {"content": "Custom audience claim success"}}
    )()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test custom audience claim", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_audience_verification_with_multiple_audiences(jwt_test_agent):
    """Test that tokens with multiple audiences (list) work correctly."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience=["test-audience-123", "test-audience-456"],  # Multiple audiences
    )

    client = TestClient(app)

    # Create token with one of the allowed audiences
    payload = {
        "sub": "test_user_123",
        "aud": ["test-audience-123", "other-audience"],  # Contains one matching audience
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Multiple audiences success"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test multiple audiences", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()


def test_audience_verification_with_multiple_audiences_failure(jwt_test_agent):
    """Test that tokens with non-matching multiple audiences are rejected."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience=["test-audience-123", "test-audience-456"],  # Multiple audiences
    )

    client = TestClient(app)

    # Create token with non-matching audiences
    payload = {
        "sub": "test_user_123",
        "aud": ["wrong-audience-1", "wrong-audience-2"],  # None match
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "Invalid token audience" in response.json()["detail"]


def test_audience_verification_explicit_overrides_agent_os_id(jwt_test_agent):
    """Test that explicit audience parameter takes precedence over agent_os_id."""

    agent_os_id = "test-agent-os-789"
    agent_os = AgentOS(id=agent_os_id, agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience="explicit-audience-123",  # Explicit audience should override agent_os_id
    )

    client = TestClient(app)

    # Create token with explicit audience (not agent_os_id)
    payload = {
        "sub": "test_user_123",
        "aud": "explicit-audience-123",  # Matches explicit audience, not agent_os_id
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    mock_run_output = type(
        "MockRunOutput", (), {"to_dict": lambda self: {"content": "Explicit audience override success"}}
    )()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        response = client.post(
            "/agents/jwt-test-agent/runs",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": "Test explicit audience override", "stream": "false"},
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()

    # Token with agent_os_id should fail (explicit audience takes precedence)
    payload2 = {
        "sub": "test_user_123",
        "aud": agent_os_id,  # Matches agent_os_id but not explicit audience
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token2 = jwt.encode(payload2, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token2}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert "Invalid token audience" in response.json()["detail"]


def test_audience_stored_in_request_state(jwt_test_agent):
    """Test that audience claim is stored in request.state."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    @app.get("/test-audience-state")
    async def test_endpoint(request: Request):
        return {
            "audience": getattr(request.state, "audience", None),
        }

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=False,  # Don't verify, just extract
    )

    client = TestClient(app)

    payload = {
        "sub": "test_user_123",
        "aud": "test-audience-123",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.get("/test-audience-state", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["audience"] == "test-audience-123"


def test_audience_verification_missing_aud_claim(jwt_test_agent):
    """Test that tokens without aud claim are rejected with clear error when verify_audience=True."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience="test-audience-123",
    )

    client = TestClient(app)

    # Create token WITHOUT aud claim
    payload = {
        "sub": "test_user_123",
        # No "aud" claim
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert 'missing the "aud" claim' in response.json()["detail"]
    assert "Audience verification requires" in response.json()["detail"]


def test_audience_verification_missing_custom_audience_claim(jwt_test_agent):
    """Test that tokens without custom audience claim are rejected with clear error."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_id_claim="sub",
        validate=True,
        verify_audience=True,
        audience="test-audience-123",
        audience_claim="custom_aud",  # Custom audience claim name
    )

    client = TestClient(app)

    # Create token WITHOUT custom_aud claim
    payload = {
        "sub": "test_user_123",
        # No "custom_aud" claim
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "Should fail", "stream": "false"},
    )

    assert response.status_code == 401
    assert 'missing the "custom_aud" claim' in response.json()["detail"]
