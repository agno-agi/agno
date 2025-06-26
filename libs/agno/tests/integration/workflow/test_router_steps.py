"""Test Router functionality in workflows."""

import pytest

from agno.agent import Agent
from agno.run.v2.workflow import WorkflowCompletedEvent
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput
from agno.workflow.v2.workflow import Workflow


@pytest.fixture
def workflow_storage(tmp_path):
    """Create a SqliteStorage instance for workflow v2."""
    storage = SqliteStorage(table_name="workflow_v2", db_file=str(tmp_path / "test_workflow_v2.db"), mode="workflow_v2")
    storage.create()
    return storage


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    return Agent(name="TestAgent", instructions="Test agent")


@pytest.fixture
def mock_team(mock_agent):
    """Create a mock team for testing."""
    return Team(name="TestTeam", mode="coordinate", members=[mock_agent], instructions="Test team")


class TestRouter:
    """Test Router functionality."""

    def test_basic_routing(self, workflow_storage):
        """Test basic routing based on input."""

        def route_selector(step_input: StepInput):
            if "tech" in step_input.message.lower():
                return [Step(name="tech", executor=lambda x: StepOutput(content="Tech content"))]
            return [Step(name="general", executor=lambda x: StepOutput(content="General content"))]

        workflow = Workflow(
            name="Basic Router",
            storage=workflow_storage,
            steps=[Router(name="router", selector=route_selector, choices=[], description="Basic routing")],
        )

        tech_response = workflow.run(message="tech topic")
        assert tech_response.step_responses[0][0].content == "Tech content"

        general_response = workflow.run(message="general topic")
        assert general_response.step_responses[0][0].content == "General content"

    def test_streaming(self, workflow_storage):
        """Test router with streaming."""

        def route_selector(step_input: StepInput):
            return [Step(name="stream", executor=lambda x: StepOutput(content="Stream content"))]

        workflow = Workflow(
            name="Stream Router",
            storage=workflow_storage,
            steps=[Router(name="router", selector=route_selector, choices=[], description="Stream routing")],
        )

        events = list(workflow.run(message="test", stream=True))
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert completed_events[0].content is not None

    def test_agent_routing(self, workflow_storage, mock_agent):
        """Test routing to agent steps."""

        def route_selector(step_input: StepInput):
            return [Step(name="agent_step", agent=mock_agent)]

        workflow = Workflow(
            name="Agent Router",
            storage=workflow_storage,
            steps=[Router(name="router", selector=route_selector, choices=[], description="Agent routing")],
        )

        response = workflow.run(message="test")
        assert response.step_responses[0][0].success

    def test_mixed_routing(self, workflow_storage, mock_agent, mock_team):
        """Test routing to mix of function, agent, and team."""

        def route_selector(step_input: StepInput):
            return [
                Step(name="function", executor=lambda x: StepOutput(content="Function output")),
                Step(name="agent", agent=mock_agent),
                Step(name="team", team=mock_team),
            ]

        workflow = Workflow(
            name="Mixed Router",
            storage=workflow_storage,
            steps=[Router(name="router", selector=route_selector, choices=[], description="Mixed routing")],
        )

        response = workflow.run(message="test")
        router_outputs = response.step_responses[0]
        assert len(router_outputs) == 3
        assert "Function output" in router_outputs[0].content
        assert router_outputs[1].success  # Agent step
        assert router_outputs[2].success  # Team step
