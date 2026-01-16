"""Unit tests for TrailingSlashMiddleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agno.os.middleware.trailing_slash import TrailingSlashMiddleware


def homepage(request):
    """Simple homepage handler."""
    return PlainTextResponse(f"Path: {request.url.path}")


def agents_handler(request):
    """Agents endpoint handler."""
    return PlainTextResponse(f"Agents - Path: {request.url.path}")


def agent_runs_handler(request):
    """Agent runs endpoint handler."""
    agent_id = request.path_params.get("agent_id", "unknown")
    return PlainTextResponse(f"Agent {agent_id} runs - Path: {request.url.path}")


@pytest.fixture
def app():
    """Create a test app with trailing slash middleware."""
    routes = [
        Route("/", homepage),
        Route("/agents", agents_handler),
        Route("/agents/{agent_id}/runs", agent_runs_handler),
        Route("/health", homepage),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(TrailingSlashMiddleware)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app, raise_server_exceptions=False)


def test_root_path_not_modified(client):
    """Root path '/' should not be modified."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Path: /" in response.text


def test_path_without_trailing_slash(client):
    """Paths without trailing slash should work normally."""
    response = client.get("/agents")
    assert response.status_code == 200
    assert "Path: /agents" in response.text


def test_path_with_trailing_slash_stripped(client):
    """Paths with trailing slash should be stripped and route correctly."""
    response = client.get("/agents/")
    assert response.status_code == 200
    # The middleware strips the trailing slash, so the path seen by handler is /agents
    assert "Path: /agents" in response.text


def test_health_endpoint_with_trailing_slash(client):
    """Health endpoint should work with trailing slash."""
    response = client.get("/health/")
    assert response.status_code == 200
    assert "Path: /health" in response.text


def test_path_params_with_trailing_slash(client):
    """Path parameters should work correctly with trailing slash."""
    response = client.get("/agents/test-agent-123/runs/")
    assert response.status_code == 200
    assert "Agent test-agent-123 runs" in response.text
    assert "Path: /agents/test-agent-123/runs" in response.text


def test_path_params_without_trailing_slash(client):
    """Path parameters should work correctly without trailing slash."""
    response = client.get("/agents/test-agent-123/runs")
    assert response.status_code == 200
    assert "Agent test-agent-123 runs" in response.text


def test_post_request_with_trailing_slash(client):
    """POST requests with trailing slash should work."""
    response = client.post("/agents/")
    # Will get 405 since we only defined GET, but the point is no redirect
    assert response.status_code == 405  # Method not allowed, not 307 redirect


def test_no_redirect_status_code(client):
    """Ensure no 307 redirect is returned for trailing slash."""
    response = client.get("/agents/")
    # Should be 200, not 307 redirect
    assert response.status_code == 200
    # Verify the response is the actual content, not a redirect response
    assert "Agents" in response.text


def test_multiple_trailing_slashes(client):
    """Multiple trailing slashes should all be stripped."""
    # Note: This depends on how rstrip works - it strips all trailing slashes
    response = client.get("/agents///")
    assert response.status_code == 200
    assert "Path: /agents" in response.text


def test_query_string_preserved(app):
    """Query strings should be preserved when trailing slash is stripped."""

    def query_handler(request):
        return PlainTextResponse(f"Query: {request.query_params.get('foo', 'none')}")

    app.routes.append(Route("/search", query_handler))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/search/?foo=bar")
    assert response.status_code == 200
    assert "Query: bar" in response.text
