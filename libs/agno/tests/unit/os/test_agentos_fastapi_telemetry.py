"""Unit tests for FastAPI native telemetry on apps built by AgentOS."""

from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.app import _is_untraced_request

pytest.importorskip("fastapi.telemetry")


@patch("agno.os.app._agno_tracing_is_active", return_value=True)
@patch("agno.os.app.setup_tracing_for_os")
def test_tracing_disables_fastapi_request_tracing(mock_setup_tracing, mock_active):
    agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=InMemoryDb(), tracing=True)

    app = agent_os.get_app()

    assert app._telemetry["tracing"] is False


@patch("agno.os.app._agno_tracing_is_active", return_value=False)
@patch("agno.os.app.setup_tracing_for_os")
def test_tracing_keeps_fastapi_request_tracing_for_the_applications_own_provider(mock_setup_tracing, mock_active):
    agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=InMemoryDb(), tracing=True)

    app = agent_os.get_app()

    assert app._telemetry["tracing"] is True


@patch("agno.os.app.setup_tracing_for_os")
def test_trace_requests_keeps_fastapi_request_tracing(mock_setup_tracing):
    db = InMemoryDb()
    agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=db, tracing=True, trace_requests=True)

    app = agent_os.get_app()

    assert app._telemetry["tracing"] is True
    mock_setup_tracing.assert_called_once_with(db=db, include_application_spans=True)


@pytest.mark.parametrize(
    "path, untraced",
    [
        ("/health", True),
        ("/traces", True),
        ("/traces/abc123", True),
        ("/trace_session_stats", True),
        ("/sessions", False),
        ("/agents/weather-agent/runs", False),
        ("/tracesfoo", False),
    ],
)
def test_trace_requests_excludes_health_and_trace_routes(path, untraced):
    assert _is_untraced_request({"path": path, "method": "GET"}) is untraced


def test_trace_requests_excludes_cors_preflights():
    assert _is_untraced_request({"path": "/sessions", "method": "OPTIONS"}) is True


def test_trace_requests_excludes_websockets():
    assert _is_untraced_request({"type": "websocket", "path": "/workflows/ws"}) is True


def test_fastapi_request_tracing_is_untouched_without_agno_tracing():
    agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=InMemoryDb())

    app = agent_os.get_app()

    assert app._telemetry["tracing"] is True
