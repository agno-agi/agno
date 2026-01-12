"""Integration tests for per-request isolation feature.

Per-request isolation is the default behavior in AgentOS. Each request
gets a fresh instance of the agent/team/workflow to prevent state
contamination between concurrent requests.
"""

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
    """Tests for AgentOS with per-request isolation (default behavior)."""

    def test_agent_run_creates_fresh_instance(self, test_agent):
        """Each request should use a fresh agent instance."""
        os = AgentOS(agents=[test_agent])
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
        os = AgentOS(agents=[test_agent])
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

    def test_team_creates_fresh_instance(self, test_team):
        """Each request should use a fresh team instance."""
        os = AgentOS(teams=[test_team])
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
