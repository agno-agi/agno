"""Integration tests for JWT middleware functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

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
        token_prefix="Bearer",
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
        token_prefix="Bearer",
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
        token_prefix="Bearer",
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
        token_prefix="Bearer",
        user_id_claim="sub",
        session_id_claim="session_id",
        dependencies_claims=["name", "email"],
        validate=True,
        excluded_route_paths=["/health"],  # Exclude health endpoint
    )

    client = TestClient(app)

    # Health endpoint should work without token (excluded)
    response = client.get("/health")
    assert response.status_code == 200

    # Agent endpoint should require token (not excluded)
    response = client.post(
        "/agents/jwt-test-agent/runs",
        data={"message": "This should fail", "stream": "false"},
    )
    assert response.status_code == 401
