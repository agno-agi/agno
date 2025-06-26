"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
from typing import AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.workflow.v2 import StepInput, StepOutput, Workflow


@pytest.fixture
def workflow_storage(tmp_path):
    """Create a SqliteStorage instance for workflow v2."""
    storage = SqliteStorage(table_name="workflow_v2", db_file=str(tmp_path / "test_workflow_v2.db"), mode="workflow_v2")
    storage.create()
    return storage


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    return Agent(name="Mock Agent", instructions="Mock response for testing")


@pytest.fixture
def mock_team(mock_agent):
    """Create a mock team for testing."""
    return Team(name="Mock Team", mode="coordinate", members=[mock_agent], instructions="Mock team response")


class TestSequences:
    """Tests for workflow sequences."""

    def test_basic_sequence(self, workflow_storage):
        """Test basic sequence with just functions."""

        def step1(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"First: {step_input.message}")

        def step2(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Second: {step_input.previous_step_content}")

        workflow = Workflow(name="Basic Sequence", storage=workflow_storage, steps=[step1, step2])

        response = workflow.run(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert len(response.step_responses) == 2
        assert "Second: First: test" in response.content

    def test_agent_sequence(self, workflow_storage, mock_agent):
        """Test sequence with function and agent."""

        def step(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Function: {step_input.message}")

        workflow = Workflow(name="Agent Sequence", storage=workflow_storage, steps=[step, mock_agent])

        response = workflow.run(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert len(response.step_responses) == 2
        assert response.step_responses[1].success

    def test_team_sequence(self, workflow_storage, mock_team):
        """Test sequence with function and team."""

        def step(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Function: {step_input.message}")

        workflow = Workflow(name="Team Sequence", storage=workflow_storage, steps=[step, mock_team])

        response = workflow.run(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert len(response.step_responses) == 2
        assert response.step_responses[1].success

    def test_streaming_sequence(self, workflow_storage):
        """Test streaming sequence."""

        def streaming_step(step_input: StepInput) -> Iterator[StepOutput]:
            yield StepOutput(content="Start")

        workflow = Workflow(name="Streaming", storage=workflow_storage, steps=[streaming_step])

        events = list(workflow.run(message="test", stream=True))
        step_events = [e for e in events if isinstance(e, StepOutput)]
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

        assert len(completed_events) == 1
        assert any("Start" in str(e.content) for e in step_events)

    @pytest.mark.asyncio
    async def test_async_sequence(self, workflow_storage):
        """Test async sequence."""

        async def async_step(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.001)
            return StepOutput(content=f"Async: {step_input.message}")

        workflow = Workflow(name="Async", storage=workflow_storage, steps=[async_step])

        response = await workflow.arun(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert "Async: test" in response.content

    @pytest.mark.asyncio
    async def test_async_streaming(self, workflow_storage):
        """Test async streaming sequence."""

        async def async_streaming_step(step_input: StepInput) -> AsyncIterator[StepOutput]:
            yield StepOutput(content="Start")

        workflow = Workflow(name="Async Streaming", storage=workflow_storage, steps=[async_streaming_step])

        events = []
        async for event in await workflow.arun(message="test", stream=True):
            events.append(event)

        step_events = [e for e in events if isinstance(e, StepOutput)]
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

        assert len(completed_events) == 1
        assert any("Start" in str(e.content) for e in step_events)

    def test_mixed_sequence(self, workflow_storage, mock_agent, mock_team):
        """Test sequence with function, agent, and team."""

        def step(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Function: {step_input.message}")

        workflow = Workflow(name="Mixed", storage=workflow_storage, steps=[step, mock_agent, mock_team])

        response = workflow.run(message="test")
        assert isinstance(response, WorkflowRunResponse)
        assert len(response.step_responses) == 3
        assert "Function: test" in response.step_responses[0].content
        assert all(step.success for step in response.step_responses[1:])
