"""Integration tests for custom FastAPI app scenarios with AgentOS."""

from contextlib import asynccontextmanager
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


@pytest.fixture
def test_agent():
    """Create a test agent."""
    return Agent(name="test-agent", db=InMemoryDb())


@pytest.fixture
def test_team(test_agent: Agent):
    """Create a test team."""
    return Team(name="test-team", members=[test_agent])


@pytest.fixture
def test_workflow():
    """Create a test workflow."""
    return Workflow(name="test-workflow")


def test_custom_app_with_cors_middleware(test_agent: Agent):
    """Test that custom CORS middleware is properly handled by AgentOS."""
    # Create custom FastAPI app with CORS middleware
    custom_app = FastAPI(title="Custom App")
    custom_app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://custom.example.com", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-Custom-Header"],
    )

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Test actual CORS request with origin header (more reliable than OPTIONS)
    response = client.get(
        "/health", headers={"Origin": "https://custom.example.com", "Access-Control-Request-Method": "GET"}
    )
    assert response.status_code == 200

    # Check that CORS headers are present in response
    # Note: header names can be case-insensitive, so check both variants
    cors_headers = {k.lower(): v for k, v in response.headers.items()}
    assert "access-control-allow-origin" in cors_headers

    # Verify CORS middleware exists (AgentOS replaces custom CORS middleware)
    cors_middleware = None
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            cors_middleware = middleware
            break

    assert cors_middleware is not None

    # AgentOS update_cors_middleware merges origins from custom middleware
    origins = cors_middleware.kwargs.get("allow_origins", [])
    assert len(origins) > 0
    # Should include the custom origin that was merged
    assert any("custom.example.com" in origin for origin in origins)


def test_cors_middleware_configuration_only(test_agent: Agent):
    """Test CORS middleware configuration without relying on OPTIONS requests."""
    # Create custom FastAPI app with CORS middleware
    custom_app = FastAPI(title="Custom App")
    custom_app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://custom.example.com"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-Custom-Header"],
    )

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()

    # Verify CORS middleware configuration after AgentOS processing
    cors_middleware = None
    for middleware in app.user_middleware:
        if middleware.cls == CORSMiddleware:
            cors_middleware = middleware
            break

    assert cors_middleware is not None

    # AgentOS update_cors_middleware should have changed the configuration
    kwargs = cors_middleware.kwargs
    assert "allow_origins" in kwargs
    assert "allow_methods" in kwargs
    assert "allow_headers" in kwargs

    # AgentOS sets allow_methods to ["*"] which includes OPTIONS
    methods = kwargs.get("allow_methods", [])
    assert methods == ["*"] or "OPTIONS" in methods

    # Origins should be preserved or merged
    origins = kwargs.get("allow_origins", [])
    assert any("custom.example.com" in origin for origin in origins)


def test_options_request_with_explicit_handler(test_agent: Agent):
    """Test OPTIONS requests with an explicit handler - explains why basic OPTIONS fail."""
    # Create custom FastAPI app with explicit OPTIONS handler
    custom_app = FastAPI(title="Custom App")

    # Add explicit OPTIONS handler for testing
    @custom_app.options("/test-endpoint")
    async def options_handler():
        return {"message": "options ok"}

    @custom_app.get("/test-endpoint")
    async def test_endpoint():
        return {"message": "get ok"}

    custom_app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://custom.example.com"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # This should work because we have an explicit OPTIONS handler
    response = client.options("/test-endpoint")
    assert response.status_code == 200

    # Regular request should also work
    response = client.get("/test-endpoint")
    assert response.status_code == 200

    # OPTIONS on /health will still fail because AgentOS health endpoint
    # doesn't define an OPTIONS handler, and CORS middleware alone
    # doesn't automatically add OPTIONS support to all endpoints


def test_custom_app_endpoints_preserved(test_agent: Agent):
    """Test that custom endpoints are preserved alongside AgentOS endpoints."""
    # Create custom FastAPI app with custom routes
    custom_app = FastAPI(title="Custom App")

    @custom_app.get("/custom")
    async def custom_endpoint():
        return {"message": "custom endpoint"}

    @custom_app.post("/customers")
    async def get_customers():
        return [
            {"id": 1, "name": "John Doe", "email": "john@example.com"},
            {"id": 2, "name": "Jane Doe", "email": "jane@example.com"},
        ]

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Test custom endpoints work
    response = client.get("/custom")
    assert response.status_code == 200
    assert response.json() == {"message": "custom endpoint"}

    response = client.post("/customers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "John Doe"

    # Test AgentOS endpoints still work
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "AgentOS API" in data["name"]


def test_route_conflicts_replace_routes_true(test_agent: Agent):
    """Test route conflict resolution when replace_routes=True (default)."""
    # Create custom FastAPI app with conflicting routes
    custom_app = FastAPI(title="Custom App")

    @custom_app.get("/")
    async def custom_home():
        return {"message": "custom home"}

    @custom_app.get("/health")
    async def custom_health():
        return {"status": "custom_ok"}

    # Create AgentOS with custom app (replace_routes=True by default)
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
        replace_routes=True,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # AgentOS routes should override custom routes
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"  # AgentOS health endpoint

    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data  # AgentOS home endpoint
    assert "AgentOS API" in data["name"]


def test_route_conflicts_replace_routes_false(test_agent: Agent):
    """Test route conflict resolution when replace_routes=False."""
    # Create custom FastAPI app with conflicting routes
    custom_app = FastAPI(title="Custom App")

    @custom_app.get("/")
    async def custom_home():
        return {"message": "custom home"}

    @custom_app.get("/health")
    async def custom_health():
        return {"status": "custom_ok"}

    # Create AgentOS with custom app and replace_routes=False
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
        replace_routes=False,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Custom routes should be preserved
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "custom_ok"  # Custom health endpoint

    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "custom home"}  # Custom home endpoint

    # Non-conflicting AgentOS routes should still be available
    response = client.post("/agents/test-agent/runs", data={"message": "hello"})
    # Should either work (200/202) or fail with specific error, not 404
    assert response.status_code != 404


def test_custom_lifespan_integration(test_agent: Agent):
    """Test custom lifespan context manager integration."""
    startup_called = False
    shutdown_called = False

    @asynccontextmanager
    async def custom_lifespan(app):
        nonlocal startup_called, shutdown_called
        startup_called = True
        yield
        shutdown_called = True

    # Create AgentOS with custom lifespan
    agent_os = AgentOS(
        agents=[test_agent],
        lifespan=custom_lifespan,
    )

    app = agent_os.get_app()

    # Test that the lifespan is properly configured
    assert app.router.lifespan_context is not None

    # Create test client to trigger lifespan events
    with TestClient(app) as client:
        # Basic test to ensure app is working
        response = client.get("/health")
        assert response.status_code == 200

    # Note: TestClient automatically calls lifespan events
    assert startup_called is True
    assert shutdown_called is True


def test_custom_app_middleware_preservation(test_agent: Agent):
    """Test that custom middleware is preserved when using custom FastAPI app."""
    custom_middleware_called = False

    async def custom_middleware(request, call_next):
        nonlocal custom_middleware_called
        custom_middleware_called = True
        response = await call_next(request)
        response.headers["X-Custom-Header"] = "present"
        return response

    # Create custom FastAPI app with middleware
    custom_app = FastAPI(title="Custom App")
    custom_app.middleware("http")(custom_middleware)

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Test that custom middleware is called
    response = client.get("/health")
    assert response.status_code == 200
    assert custom_middleware_called is True
    assert response.headers["X-Custom-Header"] == "present"


def test_available_endpoints_with_custom_app(test_agent: Agent, test_team: Team, test_workflow: Workflow):
    """Test that all expected AgentOS endpoints are available with custom app."""
    # Create custom FastAPI app
    custom_app = FastAPI(title="Custom App")

    @custom_app.get("/custom")
    async def custom_endpoint():
        return {"message": "custom"}

    # Create AgentOS with agents, teams, and workflows
    agent_os = AgentOS(
        agents=[test_agent],
        teams=[test_team],
        workflows=[test_workflow],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Test core endpoints
    response = client.get("/health")
    assert response.status_code == 200

    response = client.get("/")
    assert response.status_code == 200

    # Test custom endpoint still works
    response = client.get("/custom")
    assert response.status_code == 200
    assert response.json()["message"] == "custom"

    # Test sessions endpoint (should be available)
    response = client.get("/sessions")
    assert response.status_code != 404


def test_route_listing_with_custom_app(test_agent: Agent):
    """Test that get_routes() returns all routes including custom ones."""
    # Create custom FastAPI app
    custom_app = FastAPI(title="Custom App")

    @custom_app.get("/custom")
    async def custom_endpoint():
        return {"message": "custom"}

    @custom_app.post("/custom-post")
    async def custom_post():
        return {"result": "posted"}

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    routes = agent_os.get_routes()

    # Convert routes to paths for easier testing
    route_paths = []
    route_methods = []
    for route in routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
        if hasattr(route, "methods"):
            route_methods.extend(list(route.methods))

    # Check that both custom and AgentOS routes are present
    assert "/custom" in route_paths
    assert "/custom-post" in route_paths
    assert "/health" in route_paths
    assert "/" in route_paths

    # Check methods
    assert "GET" in route_methods
    assert "POST" in route_methods


def test_cors_origin_merging(test_agent: Agent):
    """Test CORS origin merging between custom app and AgentOS settings."""
    # Create custom FastAPI app with CORS
    custom_app = FastAPI()
    custom_app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://custom.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mock AgentOS settings with different origins
    with patch("agno.os.app.AgnoAPISettings") as mock_settings_class:
        mock_settings = Mock()
        mock_settings.docs_enabled = True
        mock_settings.cors_origin_list = ["https://agno.com", "http://localhost:3000"]
        mock_settings_class.return_value = mock_settings

        # Create AgentOS with custom app
        agent_os = AgentOS(
            agents=[test_agent],
            fastapi_app=custom_app,
            settings=mock_settings,
        )

        app = agent_os.get_app()

        # Check that CORS middleware exists and has merged origins
        cors_middleware = None
        for middleware in app.user_middleware:
            if middleware.cls == CORSMiddleware:
                cors_middleware = middleware
                break

        assert cors_middleware is not None
        origins = cors_middleware.kwargs.get("allow_origins", [])

        # Should contain origins from both custom app and settings
        # Exact merging behavior depends on implementation
        assert set(origins) == set(["https://agno.com", "http://localhost:3000", "https://custom.com"])


def test_exception_handling_with_custom_app(test_agent: Agent):
    """Test that exception handling works properly with custom FastAPI app."""
    # Create custom FastAPI app
    custom_app = FastAPI()

    @custom_app.get("/error")
    async def error_endpoint():
        raise HTTPException(status_code=400, detail="Custom error")

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Test custom error endpoint
    response = client.get("/error")
    assert response.status_code == 400
    assert "Custom error" in response.json()["detail"]

    # Test AgentOS endpoints still handle errors properly
    response = client.get("/nonexistent")
    assert response.status_code == 404


def test_custom_app_docs_configuration(test_agent: Agent):
    """Test that API docs configuration is preserved with custom FastAPI app."""
    # Create custom FastAPI app with custom docs settings
    custom_app = FastAPI(
        title="Custom API",
        version="2.0.0",
        description="Custom API Description",
        docs_url="/custom-docs",
        redoc_url="/custom-redoc",
    )

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Test custom docs endpoints
    response = client.get("/custom-docs")
    assert response.status_code == 200

    response = client.get("/custom-redoc")
    assert response.status_code == 200

    # Check that app metadata is preserved
    assert app.title == "Custom API"
    assert app.version == "2.0.0"
    assert app.description == "Custom API Description"


def test_multiple_middleware_interaction(test_agent: Agent):
    """Test interaction between custom middleware and AgentOS middleware."""
    middleware_call_order = []

    async def first_middleware(request, call_next):
        middleware_call_order.append("first")
        response = await call_next(request)
        response.headers["X-First"] = "first"
        return response

    async def second_middleware(request, call_next):
        middleware_call_order.append("second")
        response = await call_next(request)
        response.headers["X-Second"] = "second"
        return response

    # Create custom FastAPI app with multiple middleware
    custom_app = FastAPI()
    custom_app.middleware("http")(first_middleware)
    custom_app.middleware("http")(second_middleware)

    # Create AgentOS with custom app
    agent_os = AgentOS(
        agents=[test_agent],
        fastapi_app=custom_app,
    )

    app = agent_os.get_app()
    client = TestClient(app)

    # Clear call order for test
    middleware_call_order.clear()

    # Test request
    response = client.get("/health")
    assert response.status_code == 200

    # Check middleware was called
    assert len(middleware_call_order) > 0

    # Check headers from middleware
    assert "X-First" in response.headers
    assert "X-Second" in response.headers
