from unittest.mock import MagicMock, Mock

import httpx

from agno.agent import Agent
from agno.session.agent import AgentSession


def test_add_location_to_context_builds_system_message(monkeypatch):
    ip_response = Mock()
    ip_response.json.return_value = {"ip": "203.0.113.7"}
    location_response = Mock(status_code=200)
    location_response.json.return_value = {"city": "Paris", "region": "Ile-de-France", "country": "France"}
    monkeypatch.setattr(httpx, "get", Mock(side_effect=[ip_response, location_response]))

    mock_model = MagicMock()
    mock_model.get_instructions_for_model = MagicMock(return_value=None)
    mock_model.get_system_message_for_model = MagicMock(return_value=None)
    agent = Agent(add_location_to_context=True)
    agent.model = mock_model

    message = agent.get_system_message(session=AgentSession(session_id="location-context"))

    assert message is not None
    assert "Your approximate location is: Paris, Ile-de-France, France." in message.content
