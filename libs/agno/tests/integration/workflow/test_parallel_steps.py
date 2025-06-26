"""Integration tests for Parallel steps functionality."""

import pytest

from agno.agent import Agent
from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.storage.sqlite import SqliteStorage
from agno.workflow.v2 import Workflow
from agno.workflow.v2.parallel import Parallel
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput


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


# Simple step functions for testing
def step_a(step_input: StepInput) -> StepOutput:
    """Test step A."""
    return StepOutput(content="Output A")


def step_b(step_input: StepInput) -> StepOutput:
    """Test step B."""
    return StepOutput(content="Output B")


def final_step(step_input: StepInput) -> StepOutput:
    """Combine previous outputs."""
    return StepOutput(content=f"Final: {step_input.get_all_previous_content()}")


class TestParallelSteps:
    """Test parallel step functionality."""

    def test_basic_parallel(self, workflow_storage):
        """Test basic parallel execution."""
        workflow = Workflow(
            name="Basic Parallel",
            storage=workflow_storage,
            steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
        )

        response = workflow.run(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert len(response.step_responses) == 2

        # Check parallel output
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert "Output A" in parallel_output.content
        assert "Output B" in parallel_output.content

    def test_parallel_streaming(self, workflow_storage):
        """Test parallel execution with streaming."""
        workflow = Workflow(
            name="Streaming Parallel",
            storage=workflow_storage,
            steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
        )

        events = list(workflow.run(message="test", stream=True))
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert completed_events[0].content is not None

    def test_parallel_with_agent(self, workflow_storage, mock_agent):
        """Test parallel execution with agent step."""
        agent_step = Step(name="agent_step", agent=mock_agent)

        workflow = Workflow(
            name="Agent Parallel",
            storage=workflow_storage,
            steps=[Parallel(step_a, agent_step, name="Mixed Parallel"), final_step],
        )

        response = workflow.run(message="test")
        assert isinstance(response, WorkflowRunResponse)
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert "Output A" in parallel_output.content

    @pytest.mark.asyncio
    async def test_async_parallel(self, workflow_storage):
        """Test async parallel execution."""
        workflow = Workflow(
            name="Async Parallel",
            storage=workflow_storage,
            steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
        )

        response = await workflow.arun(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert len(response.step_responses) == 2

    @pytest.mark.asyncio
    async def test_async_parallel_streaming(self, workflow_storage):
        """Test async parallel execution with streaming."""
        workflow = Workflow(
            name="Async Streaming Parallel",
            storage=workflow_storage,
            steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
        )

        events = []
        async for event in await workflow.arun(message="test", stream=True):
            events.append(event)

        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert completed_events[0].content is not None
