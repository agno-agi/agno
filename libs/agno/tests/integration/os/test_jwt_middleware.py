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
from agno.os.middleware import JWTMiddleware
from agno.os.middleware.jwt import TokenSource

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

    return Agent(
        name="jwt-test-agent",
        db=InMemoryDb(),
        instructions="You are a test agent that can access JWT information and user profiles.",
    )


@pytest.fixture
def jwt_test_client(jwt_test_agent):
    """Create a test client with JWT middleware configured."""
    # Create AgentOS with the JWT test agent
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    # Add JWT middleware
    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        algorithm="HS256",
        user_id_claim="sub",  # Extract user_id from 'sub' claim
        session_id_claim="session_id",  # Extract session_id from 'session_id' claim
        dependencies_claims=["name", "email", "roles", "org_id"],  # Extract these as dependencies
        validate=True,  # Enable token validation for this test
    )

    return TestClient(app)


def test_jwt_middleware_extracts_claims_correctly(jwt_test_client, jwt_token, jwt_test_agent):
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


def test_jwt_middleware_without_token_fails_validation(jwt_test_client):
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


def test_jwt_middleware_with_invalid_token_fails(jwt_test_client):
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


def test_jwt_middleware_with_expired_token_fails(jwt_test_client):
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


def test_jwt_middleware_validation_disabled(jwt_test_agent):
    """Test JWT middleware with validation disabled."""

    # Create AgentOS with JWT middleware but validation disabled
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
        algorithm="HS256",
        token_header_key="Authorization",
        user_id_claim="sub",
        session_id_claim="session_id",
        dependencies_claims=["name", "email", "roles"],
        validate=False,  # Disable validation
    )

    client = TestClient(app)

    # Mock the agent's arun method
    mock_run_output = type("MockRunOutput", (), {"to_dict": lambda self: {"content": "Success without validation"}})()

    with patch.object(jwt_test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_run_output

        # Request without token should succeed when validation is disabled
        response = client.post(
            "/agents/jwt-test-agent/runs",
            data={
                "message": "This should work without token",
                "stream": "false",
            },
        )

        assert response.status_code == 200, response.json()
        mock_arun.assert_called_once()


def test_jwt_middleware_custom_claims_configuration(jwt_test_agent):
    """Test JWT middleware with custom claim configurations."""

    # Create AgentOS with custom claim mappings
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_excluded_routes(jwt_test_agent):
    """Test that JWT middleware can exclude certain routes from authentication."""

    # Create AgentOS
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    # Add JWT middleware with excluded routes
    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_cookie_token_source(jwt_test_agent, jwt_token):
    """Test JWT middleware with cookie as token source."""

    # Create AgentOS with cookie-based JWT middleware
    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_cookie_missing_token_fails(jwt_test_agent):
    """Test that cookie-based middleware fails when cookie is missing."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_both_token_sources_header_first(jwt_test_agent, jwt_token):
    """Test JWT middleware with both token sources, header takes precedence."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_both_token_sources_cookie_fallback(jwt_test_agent, jwt_token):
    """Test JWT middleware with both token sources, falls back to cookie."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_both_token_sources_missing_both_fails(jwt_test_agent):
    """Test that both token sources fail when neither header nor cookie present."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_custom_cookie_name(jwt_test_agent, jwt_token):
    """Test JWT middleware with custom cookie name."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    custom_cookie_name = "custom_auth_token"
    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_cookie_invalid_token_fails(jwt_test_agent):
    """Test that cookie-based middleware fails with invalid token."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_scopes_string_format(jwt_test_agent):
    """Test JWT middleware with scopes claim as space-separated string."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_scopes_list_format(jwt_test_agent):
    """Test JWT middleware with scopes claim as list."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_no_scopes_claim(jwt_test_agent):
    """Test JWT middleware when no scopes claim is configured."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_session_state_claims(jwt_test_agent):
    """Test JWT middleware with session_state_claims extraction."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_custom_token_header_key(jwt_test_agent):
    """Test JWT middleware with custom token header key instead of Authorization."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    custom_header_key = "X-Auth-Token"
    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_malformed_authorization_header(jwt_test_agent):
    """Test JWT middleware with malformed Authorization headers."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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

    # Test header without Bearer prefix
    response = client.post(
        "/agents/jwt-test-agent/runs",
        headers={"Authorization": token},  # No Bearer prefix
        data={"message": "Test no bearer prefix", "stream": "false"},
    )
    assert response.status_code == 401


def test_jwt_middleware_missing_session_id_claim(jwt_test_agent):
    """Test JWT middleware when session_id_claim doesn't exist in token."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_general_exception_during_decode(jwt_test_agent):
    """Test JWT middleware handles general exceptions during token decode."""

    agent_os = AgentOS(agents=[jwt_test_agent])
    app = agent_os.get_app()

    app.add_middleware(
        JWTMiddleware,
        secret_key=JWT_SECRET,
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


def test_jwt_middleware_different_algorithm_rs256(jwt_test_agent):
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
        secret_key=public_pem.decode("utf-8"),  # Use public key for verification
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


def test_jwt_middleware_request_state_token_storage(jwt_test_agent):
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
        secret_key=JWT_SECRET,
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
