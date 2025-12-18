import asyncio

import httpx
import pytest

from agno.team import RemoteTeam
from agno.workflow import RemoteWorkflow

REQUEST_TIMEOUT = 60.0

# A2A agent registered in gateway (Google ADK facts agent)
A2A_AGENT_ID = "facts_agent"

# A2A team and workflow IDs (exposed by gateway via A2A interface)
A2A_TEAM_ID = "research-team"
A2A_WORKFLOW_ID = "qa-workflow"


@pytest.fixture(scope="module")
def client(gateway_url: str) -> httpx.Client:
    """Create an HTTP client for the gateway server."""
    return httpx.Client(base_url=gateway_url, timeout=REQUEST_TIMEOUT)


@pytest.fixture(scope="module")
def a2a_base_url(gateway_url: str) -> str:
    """Get the A2A endpoint URL."""
    return f"{gateway_url}/a2a"


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


class TestA2ARemoteTeam:
    """Test RemoteTeam with A2A protocol connected to gateway's A2A interface."""

    def test_a2a_remote_team_basic_messaging(self, a2a_base_url: str):
        """Test basic non-streaming message via A2A protocol to RemoteTeam."""
        # Create RemoteTeam with A2A protocol
        remote_team = RemoteTeam(
            base_url=a2a_base_url,
            team_id=A2A_TEAM_ID,
            protocol="a2a",
            timeout=REQUEST_TIMEOUT,
        )

        # Send message via A2A protocol
        result = asyncio.get_event_loop().run_until_complete(
            remote_team.arun(
                input="What is 2 + 2?",
                stream=False,
            )
        )

        # Verify response
        assert result is not None
        assert result.content is not None
        assert result.run_id is not None

    def test_a2a_remote_team_with_session(self, a2a_base_url: str):
        """Test multi-turn conversation via A2A protocol to RemoteTeam."""
        remote_team = RemoteTeam(
            base_url=a2a_base_url,
            team_id=A2A_TEAM_ID,
            protocol="a2a",
            timeout=REQUEST_TIMEOUT,
        )

        # First turn
        result1 = asyncio.get_event_loop().run_until_complete(
            remote_team.arun(
                input="Remember that my favorite number is 42.",
                stream=False,
            )
        )
        assert result1 is not None
        session_id = result1.session_id

        # Second turn with same session
        result2 = asyncio.get_event_loop().run_until_complete(
            remote_team.arun(
                input="What is my favorite number?",
                session_id=session_id,
                stream=False,
            )
        )
        assert result2 is not None
        assert result2.content is not None


class TestA2ARemoteWorkflow:
    """Test RemoteWorkflow with A2A protocol connected to gateway's A2A interface."""

    def test_a2a_remote_workflow_basic_messaging(self, a2a_base_url: str):
        """Test basic non-streaming message via A2A protocol to RemoteWorkflow."""
        # Create RemoteWorkflow with A2A protocol
        remote_workflow = RemoteWorkflow(
            base_url=a2a_base_url,
            workflow_id=A2A_WORKFLOW_ID,
            protocol="a2a",
            timeout=REQUEST_TIMEOUT,
        )

        # Send message via A2A protocol
        result = asyncio.get_event_loop().run_until_complete(
            remote_workflow.arun(
                input="What is the capital of France?",
                stream=False,
            )
        )

        # Verify response
        assert result is not None
        assert result.content is not None
        assert result.run_id is not None

    def test_a2a_remote_workflow_with_session(self, a2a_base_url: str):
        """Test multi-turn conversation via A2A protocol to RemoteWorkflow."""
        remote_workflow = RemoteWorkflow(
            base_url=a2a_base_url,
            workflow_id=A2A_WORKFLOW_ID,
            protocol="a2a",
            timeout=REQUEST_TIMEOUT,
        )

        # First turn
        result1 = asyncio.get_event_loop().run_until_complete(
            remote_workflow.arun(
                input="Remember that the secret word is 'banana'.",
                stream=False,
            )
        )
        assert result1 is not None
        session_id = result1.session_id

        # Second turn with same session
        result2 = asyncio.get_event_loop().run_until_complete(
            remote_workflow.arun(
                input="What is the secret word?",
                session_id=session_id,
                stream=False,
            )
        )
        assert result2 is not None
        assert result2.content is not None
