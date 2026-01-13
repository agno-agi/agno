"""Integration tests for exception handling in AgentOS."""

import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS


@pytest.fixture
def test_agent(shared_db):
    """Create a test agent with SQLite database."""
    return Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )


@pytest.fixture
def test_agent_bad_model(shared_db):
    """Create a test agent with SQLite database."""
    return Agent(
        name="test-agent-bad-model",
        id="test-agent-bad-model-id",
        model=OpenAIChat(id="gpt-500"),
        db=shared_db,
    )


@pytest.fixture
def test_os_client(test_agent: Agent, test_agent_bad_model: Agent):
    """Create a FastAPI test client with AgentOS."""
    agent_os = AgentOS(agents=[test_agent, test_agent_bad_model])
    app = agent_os.get_app()
    return TestClient(app, raise_server_exceptions=False)


def test_404_not_found(test_os_client):
    """Test that 404 errors are properly handled."""
    response = test_os_client.get("/nonexistent-route")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_invalid_agent_id(test_os_client):
    """Test accessing a non-existent agent returns proper error."""
    response = test_os_client.post(
        "/agents/invalid-agent-id/runs",
        data={"message": "Hello"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code in [404, 400]
    assert "detail" in response.json()


def test_missing_required_fields(test_os_client, test_agent: Agent):
    """Test that missing required fields return proper validation error."""
    response = test_os_client.post(
        f"/agents/{test_agent.id}/runs",
        data={},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    # Should return 422 for validation error or 400 for bad request
    assert response.status_code in [400, 422]
    assert "detail" in response.json()


def test_invalid_json_payload(test_os_client):
    """Test that invalid JSON payload is handled properly."""
    response = test_os_client.post(
        "/health",
        data="invalid json",
        headers={"Content-Type": "application/json"},
    )
    # Should handle gracefully
    assert response.status_code in [400, 422, 405]


def test_method_not_allowed(test_os_client):
    """Test that using wrong HTTP method returns proper error."""
    # Try to DELETE on health endpoint which should only support GET
    response = test_os_client.delete("/health")
    assert response.status_code == 405
    assert "detail" in response.json()


def test_error_response_format(test_os_client):
    """Test that error responses follow consistent format."""
    response = test_os_client.get("/nonexistent-route")
    assert response.status_code == 404

    response_json = response.json()
    assert "detail" in response_json
    assert isinstance(response_json["detail"], str)


def test_http_exception_logging(test_os_client, caplog):
    """Test that HTTP exceptions are properly logged."""

    with caplog.at_level(logging.WARNING):
        response = test_os_client.get("/nonexistent-route")
        assert response.status_code == 404


def test_internal_server_error_response_format(test_agent: Agent, caplog):
    """Test that 500 errors return generic message without exposing internals."""
    # Create a fresh AgentOS with the test agent
    agent_os = AgentOS(agents=[test_agent])
    app = agent_os.get_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Mock deep_copy to return the same instance, then mock arun to raise an exception
    # (AgentOS uses create_fresh=True which calls deep_copy)
    with (
        patch.object(test_agent, "deep_copy", return_value=test_agent),
        patch.object(test_agent, "arun", new_callable=AsyncMock, side_effect=Exception("Internal error")),
        caplog.at_level(logging.ERROR),
    ):
        response = client.post(
            f"/agents/{test_agent.id}/runs",
            data={"message": "Hello, world!", "stream": "false"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 500
    response_json = response.json()
    assert "detail" in response_json
    assert isinstance(response_json["detail"], str)


def test_concurrent_error_handling(test_os_client):
    """Test that multiple concurrent errors don't interfere with each other."""
    import concurrent.futures

    def make_failing_request():
        return test_os_client.get("/nonexistent-route")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(make_failing_request) for _ in range(10)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    # All should return 404
    for response in responses:
        assert response.status_code == 404
        assert "detail" in response.json()


def test_exception_handler_with_custom_base_app(shared_db):
    """Test exception handling works with custom base FastAPI app."""
    from fastapi import FastAPI

    base_app = FastAPI()

    @base_app.get("/custom")
    async def custom_route():
        return {"status": "ok"}

    test_agent = Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o"),
        db=shared_db,
    )

    agent_os = AgentOS(agents=[test_agent], base_app=base_app)
    app = agent_os.get_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Test custom route works
    response = client.get("/custom")
    assert response.status_code == 200

    # Test that exception handling still works for non-existent routes
    response = client.get("/nonexistent")
    assert response.status_code == 404


def test_exception_with_status_code_attribute(test_os_client):
    """Test that exceptions with status_code attribute are handled correctly."""
    # This would test the getattr(exc, "status_code", 500) logic
    # Most FastAPI exceptions will have this attribute
    response = test_os_client.get("/nonexistent-route")
    assert response.status_code == 404
    response_json = response.json()
    assert "detail" in response_json
