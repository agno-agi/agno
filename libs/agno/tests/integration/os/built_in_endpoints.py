from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.team.team import Team
from agno.workflow.workflow import Workflow


@pytest.fixture
def test_agent():
    """Create a test agent."""
    return Agent(name="test-agent")


@pytest.fixture
def test_team(test_agent: Agent):
    """Create a test team."""
    return Team(name="test-team", members=[test_agent])


@pytest.fixture
def test_workflow():
    """Create a test workflow."""
    return Workflow(name="test-workflow")


@pytest.fixture
def test_os_client(test_agent: Agent, test_team: Team, test_workflow: Workflow):
    """Create a FastAPI test client."""
    agent_os = AgentOS(agents=[test_agent], teams=[test_team], workflows=[test_workflow])
    app = agent_os.get_app()
    return TestClient(app)


def test_create_agent_run_with_kwargs(test_agent: Agent, test_os_client: TestClient):
    """Test that the create_agent_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            "/agents/test-agent/runs",
            data={
                "message": "Hello, world!",
                "stream": "false",
                # Passing some extra fields to the run endpoint
                "extra_field": "foo",
                "extra_field_two": "bar",
            },
        )
        assert response.status_code == 200

        # Asserting our extra fields were passed as kwargs
        call_args = mock_arun.call_args
        assert call_args.kwargs["extra_field"] == "foo"
        assert call_args.kwargs["extra_field_two"] == "bar"


def test_create_agent_run_with_kwargs_streaming(test_agent: Agent, test_os_client: TestClient):
    """Test that the create_agent_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            "/agents/test-agent/runs",
            data={
                "message": "Hello, world!",
                "stream": "true",
                # Passing some extra fields to the run endpoint
                "extra_field": "foo",
                "extra_field_two": "bar",
            },
        )
        assert response.status_code == 200

        # Asserting our extra fields were passed as kwargs
        call_args = mock_arun.call_args
        assert call_args.kwargs["extra_field"] == "foo"
        assert call_args.kwargs["extra_field_two"] == "bar"


def test_create_team_run_with_kwargs(test_team: Team, test_os_client: TestClient):
    """Test that the create_agent_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    with patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            "/teams/test-team/runs",
            data={
                "message": "Hello, world!",
                "stream": "false",
                # Passing some extra fields to the run endpoint
                "extra_field": "foo",
                "extra_field_two": "bar",
            },
        )
        assert response.status_code == 200

        # Asserting our extra fields were passed as kwargs
        call_args = mock_arun.call_args
        assert call_args.kwargs["extra_field"] == "foo"
        assert call_args.kwargs["extra_field_two"] == "bar"


def test_create_workflow_run_with_kwargs(test_workflow: Workflow, test_os_client: TestClient):
    """Test that the create_agent_run endpoint accepts kwargs."""

    class MockRunOutput:
        def to_dict(self):
            return {}

    with patch.object(test_workflow, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = MockRunOutput()

        response = test_os_client.post(
            "/workflows/test-workflow/runs",
            data={
                "message": "Hello, world!",
                "stream": "false",
                # Passing some extra fields to the run endpoint
                "extra_field": "foo",
                "extra_field_two": "bar",
            },
        )
        assert response.status_code == 200

        # Asserting our extra fields were passed as kwargs
        call_args = mock_arun.call_args
        assert call_args.kwargs["extra_field"] == "foo"
        assert call_args.kwargs["extra_field_two"] == "bar"
