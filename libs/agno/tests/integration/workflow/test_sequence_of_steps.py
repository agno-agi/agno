"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
import os
from typing import AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.v2.workflow import (
    WorkflowCompletedEvent,
    WorkflowRunResponse,
)
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2 import Step, StepInput, StepOutput, Workflow


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file path."""
    db_file = tmp_path / "test_workflow_v2.db"
    yield str(db_file)


@pytest.fixture
def workflow_storage(temp_db_path):
    """Create a SqliteStorage instance for workflow v2."""
    storage = SqliteStorage(table_name="workflow_v2",
                            db_file=temp_db_path, mode="workflow_v2")
    storage.create()
    return storage


@pytest.fixture
def hackernews_agent():
    """Create a real HackerNews agent for testing."""
    return Agent(
        name="Hackernews Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[HackerNewsTools()],
        role="Extract key insights and content from Hackernews posts",
    )


@pytest.fixture
def web_agent():
    """Create a real web search agent for testing."""
    return Agent(
        name="Web Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools()],
        role="Search the web for the latest news and trends",
    )


@pytest.fixture
def content_planner():
    """Create a real content planning agent."""
    return Agent(
        name="Content Planner",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "Plan a content schedule over 4 weeks for the provided topic and research content",
            "Ensure that I have posts for 3 posts per week",
        ],
    )


@pytest.fixture
def research_team(hackernews_agent, web_agent):
    """Create a real research team for testing."""
    return Team(
        name="Research Team",
        mode="coordinate",
        members=[hackernews_agent, web_agent],
        instructions="Research tech topics from Hackernews and the web",
    )


# Simple test functions for step executors
def research_function_step(step_input: StepInput) -> StepOutput:
    """Simple research function step."""
    topic = step_input.message
    return StepOutput(
        content=f"Research findings for {topic}:\n- Key trend 1: AI automation\n- Key trend 2: Cloud computing"
    )


def content_planning_function_step(step_input: StepInput) -> StepOutput:
    """Simple content planning function step."""
    research_content = step_input.previous_step_content
    return StepOutput(
        content=f"Content Plan:\n\nBased on: {research_content}\n\nWeek 1: AI deep dive\nWeek 2: Cloud trends"
    )


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
class TestSequenceOfStepsIntegration:
    """Integration tests for sequence of steps functionality using real agents."""

    def test_sync_sequence_with_agents_non_streaming(self, hackernews_agent, content_planner, workflow_storage):
        """Test sync sequence with real agents (non-streaming) - matches cookbook example."""
        # Create steps similar to cookbook
        research_step = Step(name="Research Step", agent=hackernews_agent)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        # Create workflow like cookbook
        workflow = Workflow(
            name="Content Creation Workflow",
            description="Automated content creation from blog posts to social media",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        # Execute workflow
        response = workflow.run(message="AI trends in 2024")

        # Verify response
        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.workflow_name == "Content Creation Workflow"
        assert len(response.step_responses) == 2
        # Verify actual content was generated
        assert len(response.content) > 50  # Should have substantial content

    def test_sync_sequence_with_agents_streaming(self, hackernews_agent, content_planner, workflow_storage):
        """Test sync sequence with real agents (streaming)."""
        research_step = Step(name="Research Step", agent=hackernews_agent)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        # Execute with streaming
        events = list(workflow.run(message="AI trends in 2024", stream=True))

        # Verify we get events and final completion
        assert len(events) > 0
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        # Verify actual content was generated
        assert len(completed_events[0].content) > 50

    def test_sync_sequence_with_team_non_streaming(self, research_team, content_planner, workflow_storage):
        """Test sync sequence with real team (non-streaming) - matches cookbook example."""
        # Create steps with team like cookbook
        research_step = Step(name="Research Step", team=research_team)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        response = workflow.run(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 2
        # Verify actual content was generated by team
        assert len(response.content) > 50

    def test_sync_sequence_with_team_streaming(self, research_team, content_planner, workflow_storage):
        """Test sync sequence with real team (streaming)."""
        research_step = Step(name="Research Step", team=research_team)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        events = list(workflow.run(message="AI trends in 2024", stream=True))

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert len(completed_events[0].content) > 50

    @pytest.mark.asyncio
    async def test_async_sequence_with_agents_non_streaming(self, hackernews_agent, content_planner, workflow_storage):
        """Test async sequence with real agents (non-streaming)."""
        research_step = Step(name="Research Step", agent=hackernews_agent)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        response = await workflow.arun(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 2
        assert len(response.content) > 50

    @pytest.mark.asyncio
    async def test_async_sequence_with_agents_streaming(self, hackernews_agent, content_planner, workflow_storage):
        """Test async sequence with real agents (streaming)."""
        research_step = Step(name="Research Step", agent=hackernews_agent)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        events = []
        async for event in await workflow.arun(message="AI trends in 2024", stream=True):
            events.append(event)

        assert len(events) > 0
        # Check that we get meaningful events
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        if completed_events:
            assert len(completed_events[0].content) > 50

    @pytest.mark.asyncio
    async def test_async_sequence_with_team_non_streaming(self, research_team, content_planner, workflow_storage):
        """Test async sequence with real team (non-streaming)."""
        research_step = Step(name="Research Step", team=research_team)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        response = await workflow.arun(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 2
        assert len(response.content) > 50

    @pytest.mark.asyncio
    async def test_async_sequence_with_team_streaming(self, research_team, content_planner, workflow_storage):
        """Test async sequence with real team (streaming)."""
        research_step = Step(name="Research Step", team=research_team)
        content_planning_step = Step(
            name="Content Planning Step", agent=content_planner)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        events = []
        async for event in await workflow.arun(message="AI trends in 2024", stream=True):
            events.append(event)

        assert len(events) > 0


class TestSequenceOfStepsWithFunctions:
    """Test sequence of steps with function executors (no API calls needed)."""

    def test_sync_sequence_with_functions_non_streaming(self, workflow_storage):
        """Test sync sequence with function executors (non-streaming)."""
        research_step = Step(name="Research Step",
                             executor=research_function_step)
        content_planning_step = Step(
            name="Content Planning Step", executor=content_planning_function_step)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        response = workflow.run(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert "Research findings for AI trends in 2024" in response.content
        assert "Content Plan:" in response.content
        assert "Week 1:" in response.content

    def test_sync_sequence_with_functions_streaming(self, workflow_storage):
        """Test sync sequence with function executors (streaming)."""
        research_step = Step(name="Research Step",
                             executor=research_function_step)
        content_planning_step = Step(
            name="Content Planning Step", executor=content_planning_function_step)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        events = list(workflow.run(message="AI trends in 2024", stream=True))

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

        # Check final content
        final_content = completed_events[0].content
        assert "Research findings" in final_content
        assert "Content Plan:" in final_content

    @pytest.mark.asyncio
    async def test_async_sequence_with_functions_non_streaming(self, workflow_storage):
        """Test async sequence with function executors (non-streaming)."""

        async def async_research_step(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)  # Simulate async work
            topic = step_input.message
            return StepOutput(
                content=f"Async research findings for {topic}:\n- Key trend 1: AI automation\n- Key trend 2: Cloud computing"
            )

        async def async_content_planning_step(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)  # Simulate async work
            research_content = step_input.previous_step_content
            return StepOutput(
                content=f"Async Content Plan:\n\nBased on: {research_content}\n\nWeek 1: AI deep dive\nWeek 2: Cloud trends"
            )

        research_step = Step(name="Research Step",
                             executor=async_research_step)
        content_planning_step = Step(
            name="Content Planning Step", executor=async_content_planning_step)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        response = await workflow.arun(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert "Async research findings" in response.content
        assert "Async Content Plan:" in response.content

    @pytest.mark.asyncio
    async def test_async_sequence_with_functions_streaming(self, workflow_storage):
        """Test async sequence with function executors (streaming)."""

        async def async_research_step(step_input: StepInput) -> AsyncIterator[str]:
            topic = step_input.message
            yield f"Starting research on {topic}...\n"
            await asyncio.sleep(0.01)
            yield f"Research complete for {topic}.\n"

        async def async_content_planning_step(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)
            prev_content = step_input.previous_step_content or ""
            return StepOutput(content=f"Content plan based on:\n{prev_content}\nWeek 1: AI focus")

        research_step = Step(name="Research Step",
                             executor=async_research_step)
        content_planning_step = Step(
            name="Content Planning Step", executor=async_content_planning_step)

        workflow = Workflow(
            name="Content Creation Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        events = []
        async for event in await workflow.arun(message="AI trends in 2024", stream=True):
            events.append(event)

        assert len(events) > 0

