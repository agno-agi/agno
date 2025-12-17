import httpx
import pytest

REQUEST_TIMEOUT = 60.0

# A2A agent registered in gateway (Google ADK facts agent)
A2A_AGENT_ID = "facts_agent"


@pytest.fixture(scope="module")
def client(gateway_url: str) -> httpx.Client:
    """Create an HTTP client for the gateway server."""
    return httpx.Client(base_url=gateway_url, timeout=REQUEST_TIMEOUT)


class TestA2ARemoteAgentGoogleADK:
    """Test A2A RemoteAgent connected to Google ADK server."""

    def test_a2a_agent_listed(self, client: httpx.Client):
        """Test that the ADK A2A agent is listed in gateway agents."""
        response = client.get("/agents")
        assert response.status_code == 200
        agents = response.json()
        agent_ids = [a["id"] for a in agents]
        assert A2A_AGENT_ID in agent_ids

    def test_a2a_agent_info(self, client: httpx.Client):
        """Test getting ADK A2A agent info."""
        response = client.get(f"/agents/{A2A_AGENT_ID}")
        assert response.status_code == 200
        agent = response.json()
        assert agent["id"] == A2A_AGENT_ID

    def test_a2a_basic_messaging(self, client: httpx.Client):
        """Test basic non-streaming message via A2A protocol to Google ADK."""
        response = client.post(
            f"/agents/{A2A_AGENT_ID}/runs",
            data={
                "message": "Tell me an interesting fact about space.",
                "stream": "false",
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["content"] is not None
        assert "run_id" in result
        assert "session_id" in result

    def test_a2a_multi_turn(self, client: httpx.Client):
        """Test multi-turn conversation with session_id via A2A protocol."""
        # First turn - establish context
        response1 = client.post(
            f"/agents/{A2A_AGENT_ID}/runs",
            data={
                "message": "My favorite planet is Saturn. Remember this.",
                "stream": "false",
            },
        )
        assert response1.status_code == 200
        result1 = response1.json()
        session_id = result1["session_id"]
        assert session_id is not None

        # Second turn - use same session
        response2 = client.post(
            f"/agents/{A2A_AGENT_ID}/runs",
            data={
                "message": "What is my favorite planet?",
                "session_id": session_id,
                "stream": "false",
            },
        )
        assert response2.status_code == 200
        result2 = response2.json()
        assert result2["session_id"] == session_id
        assert result2["content"] is not None
