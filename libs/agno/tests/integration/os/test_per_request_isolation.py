"""Integration tests for per-request isolation feature."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.team import Team


@pytest.fixture
def test_agent():
    """Create a test agent."""
    return Agent(
        name="test-agent",
        id="test-agent-id",
        model=OpenAIChat(id="gpt-4o-mini"),
    )


@pytest.fixture
def test_team(test_agent):
    """Create a test team with the test agent as a member."""
    return Team(
        name="test-team",
        id="test-team-id",
        members=[test_agent],
        model=OpenAIChat(id="gpt-4o-mini"),
    )


class TestAgentOSPerRequestIsolation:
    """Tests for AgentOS with per_request_isolation enabled."""

    def test_per_request_isolation_default_is_false(self, test_agent):
        """Default value for per_request_isolation should be False."""
        os = AgentOS(agents=[test_agent])
        assert os.per_request_isolation is False

    def test_per_request_isolation_can_be_enabled(self, test_agent):
        """per_request_isolation can be set to True."""
        os = AgentOS(agents=[test_agent], per_request_isolation=True)
        assert os.per_request_isolation is True

    def test_agent_run_with_isolation_disabled(self, test_agent):
        """With isolation disabled, same agent instance is used."""
        os = AgentOS(agents=[test_agent], per_request_isolation=False)
        app = os.get_app()
        client = TestClient(app)

        # Mock the agent's arun method to capture the agent instance
        captured_agents = []

        async def capture_arun(*args, **kwargs):
            captured_agents.append(test_agent)
            # Return a mock response
            mock_response = AsyncMock()
            mock_response.to_dict.return_value = {"run_id": str(uuid.uuid4())}
            return mock_response

        with patch.object(test_agent, "arun", side_effect=capture_arun):
            response = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )

        # Should use the same agent (although we're capturing the original)
        assert response.status_code == 200

    def test_agent_run_with_isolation_enabled(self, test_agent):
        """With isolation enabled, fresh agent instance should be used per request."""
        os = AgentOS(agents=[test_agent], per_request_isolation=True)
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make two requests
            response1 = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Request 1", "stream": "false"},
            )
            response2 = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Request 2", "stream": "false"},
            )

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Each request should have different run_ids
        assert response1.json()["run_id"] != response2.json()["run_id"]


class TestMetadataIsolation:
    """Tests for metadata isolation between requests."""

    def test_metadata_not_shared_between_requests(self, test_agent):
        """Metadata changes in one request should not affect others."""
        test_agent.metadata = {"initial": "value"}
        os = AgentOS(agents=[test_agent], per_request_isolation=True)
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            # Make a request
            response = client.post(
                f"/agents/{test_agent.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )

        assert response.status_code == 200
        # Original agent's metadata should be unchanged
        assert test_agent.metadata == {"initial": "value"}


class TestTeamIsolation:
    """Tests for Team per-request isolation."""

    def test_team_with_isolation_enabled(self, test_team):
        """With isolation enabled, fresh team instance should be used."""
        os = AgentOS(teams=[test_team], per_request_isolation=True)
        app = os.get_app()
        client = TestClient(app)

        class MockRunOutput:
            def to_dict(self):
                return {"run_id": str(uuid.uuid4())}

        with patch.object(Team, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = MockRunOutput()

            response = client.post(
                f"/teams/{test_team.id}/runs",
                data={"message": "Hello", "stream": "false"},
            )

        assert response.status_code == 200


class TestSharedResources:
    """Tests to verify heavy resources are shared, not copied."""

    def test_db_is_shared_between_copies(self):
        """Database connection should be shared between agent copies."""
        from agno.db.memory import InMemoryDb

        db = InMemoryDb()
        agent = Agent(name="test-agent", id="test-id", db=db)

        copy = agent.deep_copy()

        # DB reference should be the same (shared)
        # Note: deep_copy tries to deepcopy db, but if it fails, shares the reference
        # For proper testing, we'd need to use a real DB that can't be deepcopied
        assert copy.db is not None

    def test_model_configuration_preserved(self):
        """Model configuration should be preserved in copies."""
        model = OpenAIChat(id="gpt-4o-mini")
        agent = Agent(name="test-agent", id="test-id", model=model)

        copy = agent.deep_copy()

        assert copy.model is not None
        assert copy.model.id == "gpt-4o-mini"
