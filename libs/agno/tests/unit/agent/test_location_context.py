"""Tests for `add_location_to_context` on the system message path."""

from unittest.mock import MagicMock, Mock

import httpx

from agno.agent import Agent
from agno.session.agent import AgentSession


def _agent_with_mock_model() -> Agent:
    mock_model = MagicMock()
    mock_model.get_instructions_for_model = MagicMock(return_value=None)
    mock_model.get_system_message_for_model = MagicMock(return_value=None)
    agent = Agent(add_location_to_context=True)
    agent.model = mock_model
    return agent


def test_add_location_to_context_builds_system_message(monkeypatch):
    ip_response = Mock()
    ip_response.json.return_value = {"ip": "203.0.113.7"}
    location_response = Mock(status_code=200)
    location_response.json.return_value = {"city": "Paris", "region": "Ile-de-France", "country": "France"}
    monkeypatch.setattr(httpx, "get", Mock(side_effect=[ip_response, location_response]))

    message = _agent_with_mock_model().get_system_message(session=AgentSession(session_id="location-context"))

    assert message is not None
    assert "Your approximate location is: Paris, Ile-de-France, France." in message.content


def test_a_failed_lookup_drops_the_location_line_and_not_the_run(monkeypatch):
    """The helper runs inline while the system message is assembled, so a
    failed lookup has to leave the message buildable without a location line
    rather than raise into the run."""
    monkeypatch.setattr(httpx, "get", Mock(side_effect=httpx.ConnectError("offline")))
    agent = Agent(add_location_to_context=True, description="A helpful assistant.")
    mock_model = MagicMock()
    mock_model.get_instructions_for_model = MagicMock(return_value=None)
    mock_model.get_system_message_for_model = MagicMock(return_value=None)
    agent.model = mock_model

    message = agent.get_system_message(session=AgentSession(session_id="location-offline"))

    assert message is not None
    assert "A helpful assistant." in message.content
    assert "Your approximate location is" not in message.content
