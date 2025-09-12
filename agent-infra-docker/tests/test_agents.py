"""
Integration tests for agent endpoints.
"""

import urllib.parse

from . import get_api_url


def test_web_agent_creation(api_client):
    """Test that the web agent can be created and accessed."""
    # Test agent list endpoint
    response = api_client.get(get_api_url("/agents"))
    assert response.status_code == 200
    agents = response.json()
    assert "web-search-agent" in [agent.get("id") for agent in agents]


def test_web_agent_search_query(api_client):
    """Test web agent with a simple search query using form data."""
    form_data = {"message": "What is the current weather in New York?", "user_id": "test_user_123"}
    payload = urllib.parse.urlencode(form_data)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = api_client.post(
        get_api_url("/agents/web-search-agent/runs"),
        headers=headers,
        data=payload,
    )
    assert response.status_code == 200, response.text

    result = response.json()
    assert "content" in result
    assert "agent_id" in result
    assert result["agent_id"] == "web-search-agent"


def test_web_agent_conversation_history(api_client):
    """Test web agent maintains conversation history."""
    user_id = "test_user_456"

    # First message
    query1 = {"message": "What is the capital of France?", "user_id": user_id}
    payload = urllib.parse.urlencode(query1)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response1 = api_client.post(
        get_api_url("/agents/web-search-agent/runs"),
        headers=headers,
        data=payload,
    )
    assert response1.status_code == 200

    # Second message referencing the first
    query2 = {"message": "What is the population of that city?", "user_id": user_id}
    payload = urllib.parse.urlencode(query2)
    response2 = api_client.post(
        get_api_url("/agents/web-search-agent/runs"),
        headers=headers,
        data=payload,
    )
    assert response2.status_code == 200

    result2 = response2.json()
    assert "content" in result2
