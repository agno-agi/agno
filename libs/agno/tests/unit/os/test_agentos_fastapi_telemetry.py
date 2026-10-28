"""Unit tests for FastAPI native telemetry on apps built by AgentOS."""

from unittest.mock import patch

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS

pytest.importorskip("fastapi.telemetry")


@patch("agno.os.app.setup_tracing_for_os")
def test_tracing_disables_fastapi_request_tracing(mock_setup_tracing):
    agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=InMemoryDb(), tracing=True)

    app = agent_os.get_app()

    assert app._telemetry["tracing"] is False


def test_fastapi_request_tracing_is_untouched_without_agno_tracing():
    agent_os = AgentOS(agents=[Agent(name="test-agent", id="test-agent-id")], db=InMemoryDb())

    app = agent_os.get_app()

    assert app._telemetry["tracing"] is True
