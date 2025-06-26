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
    storage = SqliteStorage(
        table_name="workflow_v2",
        db_file=str(tmp_path / "test_workflow_v2.db"),
        mode="workflow_v2"
    )
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
        tech_step = Step(
            name="tech",
            executor=lambda x: StepOutput(content="Tech content")
        )
        general_step = Step(
            name="general",
            executor=lambda x: StepOutput(content="General content")
        )

        def route_selector(step_input: StepInput):
            """Select between tech and general steps."""
            if "tech" in step_input.message.lower():
                return [tech_step]
            return [general_step]

        workflow = Workflow(
            name="Basic Router",
            storage=workflow_storage,
            steps=[
                Router(
                    name="router",
                    selector=route_selector,
                    choices=[tech_step, general_step],
                    description="Basic routing"
                )
            ]
        )

        tech_response = workflow.run(message="tech topic")
        assert tech_response.step_responses[0][0].content == "Tech content"

        general_response = workflow.run(message="general topic")
        assert general_response.step_responses[0][0].content == "General content"

    def test_streaming(self, workflow_storage):
        """Test router with streaming."""
        stream_step = Step(
            name="stream",
            executor=lambda x: StepOutput(content="Stream content")
        )
        alt_step = Step(
            name="alt",
            executor=lambda x: StepOutput(content="Alt content")
        )

        def route_selector(step_input: StepInput):
            return [stream_step]

        workflow = Workflow(
            name="Stream Router",
            storage=workflow_storage,
            steps=[
                Router(
                    name="router",
                    selector=route_selector,
                    choices=[stream_step, alt_step],
                    description="Stream routing"
                )
            ]
        )

        events = list(workflow.run(message="test", stream=True))
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Stream content" in completed_events[0].content

    def test_agent_routing(self, workflow_storage, mock_agent):
        """Test routing to agent steps."""
        agent_step = Step(name="agent_step", agent=mock_agent)
        function_step = Step(
            name="function_step",
            executor=lambda x: StepOutput(content="Function output")
        )

        def route_selector(step_input: StepInput):
            return [agent_step]

        workflow = Workflow(
            name="Agent Router",
            storage=workflow_storage,
            steps=[
                Router(
                    name="router",
                    selector=route_selector,
                    choices=[agent_step, function_step],
                    description="Agent routing"
                )
            ]
        )

        response = workflow.run(message="test")
        assert response.step_responses[0][0].success

    def test_mixed_routing(self, workflow_storage, mock_agent, mock_team):
        """Test routing to mix of function, agent, and team."""
        function_step = Step(
            name="function",
            executor=lambda x: StepOutput(content="Function output")
        )
        agent_step = Step(name="agent", agent=mock_agent)
        team_step = Step(name="team", team=mock_team)

        def route_selector(step_input: StepInput):
            if "function" in step_input.message:
                return [function_step]
            elif "agent" in step_input.message:
                return [agent_step]
            return [team_step]

        workflow = Workflow(
            name="Mixed Router",
            storage=workflow_storage,
            steps=[
                Router(
                    name="router",
                    selector=route_selector,
                    choices=[function_step, agent_step, team_step],
                    description="Mixed routing"
                )
            ]
        )

        # Test function route
        function_response = workflow.run(message="test function")
        assert "Function output" in function_response.step_responses[0][0].content

        # Test agent route
        agent_response = workflow.run(message="test agent")
        assert agent_response.step_responses[0][0].success

        # Test team route
        team_response = workflow.run(message="test team")
        assert team_response.step_responses[0][0].success

    def test_multiple_step_routing(self, workflow_storage):
        """Test routing to multiple steps."""
        research_step = Step(
            name="research",
            executor=lambda x: StepOutput(content="Research output")
        )
        analysis_step = Step(
            name="analysis",
            executor=lambda x: StepOutput(content="Analysis output")
        )
        summary_step = Step(
            name="summary",
            executor=lambda x: StepOutput(content="Summary output")
        )

        def route_selector(step_input: StepInput):
            if "research" in step_input.message:
                return [research_step, analysis_step]
            return [summary_step]

        workflow = Workflow(
            name="Multiple Steps Router",
            storage=workflow_storage,
            steps=[
                Router(
                    name="router",
                    selector=route_selector,
                    choices=[research_step, analysis_step, summary_step],
                    description="Multiple step routing"
                )
            ]
        )

        response = workflow.run(message="test research")
        assert len(response.step_responses[0]) == 2
        assert "Research output" in response.step_responses[0][0].content
        assert "Analysis output" in response.step_responses[0][1].content
