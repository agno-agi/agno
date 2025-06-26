"""Integration tests for Workflow v2 sequence of steps functionality"""

import asyncio
import os
from textwrap import dedent
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
from agno.workflow.v2 import StepInput, StepOutput, Workflow


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database file path."""
    db_file = tmp_path / "test_workflow_v2.db"
    yield str(db_file)


@pytest.fixture
def workflow_storage(temp_db_path):
    """Create a SqliteStorage instance for workflow v2."""
    storage = SqliteStorage(table_name="workflow_v2", db_file=temp_db_path, mode="workflow_v2")
    storage.create()
    return storage


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
def hackernews_agent():
    """Create a real HackerNews agent for testing."""
    return Agent(
        name="Hackernews Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[HackerNewsTools()],
        role="Extract key insights and content from Hackernews posts",
    )


@pytest.fixture
def writer_agent():
    """Create a real writer agent for testing."""
    return Agent(
        name="Writer Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Write a blog post on the topic",
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


# Step functions exactly like cookbook examples
def prepare_input_for_web_search(step_input: StepInput) -> StepOutput:
    """Prepare input for web search - matches cookbook example."""
    topic = step_input.message
    return StepOutput(
        content=dedent(f"""\
        I'm writing a blog post on the topic
        <topic>
        {topic}
        </topic>
        
        Search the web for atleast 10 articles\
        """)
    )


def prepare_input_for_writer(step_input: StepInput) -> StepOutput:
    """Prepare input for writer - matches cookbook example."""
    topic = step_input.message
    research_team_output = step_input.previous_step_content

    return StepOutput(
        content=dedent(f"""\
        I'm writing a blog post on the topic:
        <topic>
        {topic}
        </topic>
        
        Here is information from the web:
        <research_results>
        {research_team_output}
        </research_results>\
        """)
    )


# Streaming versions of step functions
def prepare_input_for_web_search_stream(step_input: StepInput) -> Iterator[StepOutput]:
    """Generator function that yields StepOutput - matches cookbook streaming example."""
    topic = step_input.message

    content = dedent(f"""\
        I'm writing a blog post on the topic
        <topic>
        {topic}
        </topic>
        
        Search the web for atleast 10 articles\
        """)

    yield StepOutput(content=content)


def prepare_input_for_writer_stream(step_input: StepInput) -> Iterator[StepOutput]:
    """Generator function that yields StepOutput - matches cookbook streaming example."""
    topic = step_input.message
    research_team_output = step_input.previous_step_content

    content = dedent(f"""\
        I'm writing a blog post on the topic:
        <topic>
        {topic}
        </topic>
        
        Here is information from the web:
        <research_results>
        {research_team_output}
        </research_results>\
        """)

    yield StepOutput(content=content)


# Async versions for comprehensive testing
async def async_prepare_input_for_web_search(step_input: StepInput) -> StepOutput:
    """Async version of prepare input for web search."""
    await asyncio.sleep(0.01)  # Simulate async work
    topic = step_input.message
    return StepOutput(
        content=dedent(f"""\
        I'm writing a blog post on the topic
        <topic>
        {topic}
        </topic>
        
        Search the web for atleast 10 articles\
        """)
    )


async def async_prepare_input_for_writer(step_input: StepInput) -> StepOutput:
    """Async version of prepare input for writer."""
    await asyncio.sleep(0.01)  # Simulate async work
    topic = step_input.message
    research_team_output = step_input.previous_step_content

    return StepOutput(
        content=dedent(f"""\
        I'm writing a blog post on the topic:
        <topic>
        {topic}
        </topic>
        
        Here is information from the web:
        <research_results>
        {research_team_output}
        </research_results>\
        """)
    )


async def async_prepare_input_for_web_search_stream(step_input: StepInput) -> AsyncIterator[StepOutput]:
    """Async generator function that yields StepOutput."""
    topic = step_input.message

    # Yield intermediate progress
    yield StepOutput(content=f"Preparing web search for: {topic}")
    await asyncio.sleep(0.01)

    # Yield final result
    content = dedent(f"""\
        I'm writing a blog post on the topic
        <topic>
        {topic}
        </topic>
        
        Search the web for atleast 10 articles\
        """)

    yield StepOutput(content=content)


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
class TestDirectStepsIntegration:
    """Integration tests for workflow using agents, teams, and functions directly in steps list."""

    def test_blog_post_workflow_non_streaming(
        self, web_agent, hackernews_agent, research_team, writer_agent, workflow_storage
    ):
        """Test the exact cookbook example - functions, teams, and agents in steps list (non-streaming)."""
        # Matches cookbook/workflows/sync/sequence_of_functions_and_agents.py exactly
        content_creation_workflow = Workflow(
            name="Blog Post Workflow",
            description="Automated blog post creation from Hackernews and the web",
            storage=workflow_storage,
            steps=[
                prepare_input_for_web_search,
                research_team,
                prepare_input_for_writer,
                writer_agent,
            ],
        )

        response = content_creation_workflow.run(message="AI trends in 2024")

        # Verify response structure
        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.workflow_name == "Blog Post Workflow"
        assert len(response.step_responses) == 4

        # Verify actual content was generated through the pipeline
        # Should have substantial blog post content
        assert len(response.content) > 100

        # Verify the pipeline worked by checking content contains elements from each step
        final_content = response.content.lower()
        assert "ai" in final_content or "artificial intelligence" in final_content

    def test_blog_post_workflow_streaming(
        self, web_agent, hackernews_agent, research_team, writer_agent, workflow_storage
    ):
        """Test the exact cookbook streaming example - functions, teams, and agents in steps list (streaming)."""
        # Matches cookbook/workflows/sync/sequence_of_functions_and_agents_stream.py exactly
        content_creation_workflow = Workflow(
            name="Blog Post Workflow",
            description="Automated blog post creation from Hackernews and the web",
            storage=workflow_storage,
            steps=[
                prepare_input_for_web_search_stream,
                research_team,
                prepare_input_for_writer_stream,
                writer_agent,
            ],
        )

        events = list(
            content_creation_workflow.run(message="AI trends in 2024", stream=True, stream_intermediate_steps=True)
        )

        # Verify we get events and final completion
        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

        # Verify actual content was generated
        final_content = completed_events[0].content
        assert len(final_content) > 100
        assert "ai" in final_content.lower() or "artificial intelligence" in final_content.lower()

    def test_mixed_steps_with_individual_agents(self, web_agent, writer_agent, workflow_storage):
        """Test workflow mixing functions and individual agents directly in steps list."""
        workflow = Workflow(
            name="Mixed Steps Workflow",
            storage=workflow_storage,
            steps=[
                prepare_input_for_web_search,
                web_agent,  # Individual agent directly in steps
                prepare_input_for_writer,
                writer_agent,  # Another agent directly in steps
            ],
        )

        response = workflow.run(message="Machine Learning innovations")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 4
        assert len(response.content) > 50

    def test_function_only_workflow(self, workflow_storage):
        """Test workflow with only function steps (no API calls needed)."""

        def step1(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Step 1 processed: {step_input.message}")

        def step2(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Step 2 processed: {step_input.previous_step_content}")

        def step3(step_input: StepInput) -> StepOutput:
            return StepOutput(content=f"Step 3 final: {step_input.previous_step_content}")

        workflow = Workflow(
            name="Function Only Workflow",
            storage=workflow_storage,
            steps=[step1, step2, step3],
        )

        response = workflow.run(message="Test input")

        assert isinstance(response, WorkflowRunResponse)
        assert "Step 3 final: Step 2 processed: Step 1 processed: Test input" in response.content
        assert len(response.step_responses) == 3

    @pytest.mark.asyncio
    async def test_async_blog_post_workflow_non_streaming(
        self, web_agent, hackernews_agent, research_team, writer_agent, workflow_storage
    ):
        """Test async version of the cookbook example."""
        content_creation_workflow = Workflow(
            name="Async Blog Post Workflow",
            storage=workflow_storage,
            steps=[
                async_prepare_input_for_web_search,
                research_team,
                async_prepare_input_for_writer,
                writer_agent,
            ],
        )

        response = await content_creation_workflow.arun(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 4
        assert len(response.content) > 100

    @pytest.mark.asyncio
    async def test_async_blog_post_workflow_streaming(
        self, web_agent, hackernews_agent, research_team, writer_agent, workflow_storage
    ):
        """Test async streaming version of the cookbook example."""
        content_creation_workflow = Workflow(
            name="Async Blog Post Workflow Streaming",
            storage=workflow_storage,
            steps=[
                async_prepare_input_for_web_search_stream,
                research_team,
                async_prepare_input_for_writer,
                writer_agent,
            ],
        )

        events = []
        async for event in await content_creation_workflow.arun(
            message="AI trends in 2024", stream=True, stream_intermediate_steps=True
        ):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert len(completed_events[0].content) > 100

    @pytest.mark.asyncio
    async def test_async_function_only_workflow(self, workflow_storage):
        """Test async workflow with only async function steps."""

        async def async_step1(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)
            return StepOutput(content=f"Async Step 1: {step_input.message}")

        async def async_step2(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)
            return StepOutput(content=f"Async Step 2: {step_input.previous_step_content}")

        workflow = Workflow(
            name="Async Function Only Workflow",
            storage=workflow_storage,
            steps=[async_step1, async_step2],
        )

        response = await workflow.arun(message="Async test input")

        assert isinstance(response, WorkflowRunResponse)
        assert "Async Step 2: Async Step 1: Async test input" in response.content
        assert len(response.step_responses) == 2

    @pytest.mark.asyncio
    async def test_async_streaming_generator_functions(self, workflow_storage):
        """Test async workflow with streaming generator functions."""

        async def async_streaming_step1(step_input: StepInput) -> AsyncIterator[StepOutput]:
            topic = step_input.message
            # Yield intermediate content (not StepOutput, so it gets accumulated)
            yield f"Processing {topic}..."
            await asyncio.sleep(0.01)
            # Yield the final StepOutput (this will be used as the final response)
            yield StepOutput(content=f"Analysis complete for {topic}")

        async def async_streaming_step2(step_input: StepInput) -> AsyncIterator[StepOutput]:
            prev_content = step_input.previous_step_content
            # Yield intermediate content (not StepOutput, so it gets accumulated)
            yield f"Building on: {prev_content}"
            await asyncio.sleep(0.01)
            # Yield the final StepOutput (this will be used as the final response)
            yield StepOutput(content=f"Final result based on: {prev_content}")

        workflow = Workflow(
            name="Async Streaming Function Workflow",
            storage=workflow_storage,
            steps=[async_streaming_step1, async_streaming_step2],
        )

        events = []
        async for event in await workflow.arun(message="Streaming test", stream=True):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

        final_content = completed_events[0].content
        assert "Final result based on" in final_content


class TestSequenceOfStepsWithoutAPIKey:
    """Tests that don't require API key - using only function executors."""

    def test_sync_function_sequence_non_streaming(self, workflow_storage):
        """Test sync sequence with function executors (non-streaming) - no API calls."""

        def research_step(step_input: StepInput) -> StepOutput:
            topic = step_input.message
            return StepOutput(
                content=f"Research findings for {topic}:\n- Key trend 1: AI automation\n- Key trend 2: Cloud computing"
            )

        def content_planning_step(step_input: StepInput) -> StepOutput:
            research_content = step_input.previous_step_content
            return StepOutput(
                content=f"Content Plan:\n\nBased on: {research_content}\n\nWeek 1: AI deep dive\nWeek 2: Cloud trends"
            )

        workflow = Workflow(
            name="Function Based Workflow",
            storage=workflow_storage,
            steps=[research_step, content_planning_step],
        )

        response = workflow.run(message="AI trends in 2024")

        assert isinstance(response, WorkflowRunResponse)
        assert "Research findings for AI trends in 2024" in response.content
        assert "Content Plan:" in response.content
        assert "Week 1:" in response.content

    def test_sync_function_sequence_streaming(self, workflow_storage):
        """Test sync sequence with streaming function executors - no API calls."""

        def research_step_stream(step_input: StepInput) -> Iterator[StepOutput]:
            topic = step_input.message
            yield StepOutput(content=f"Starting research on {topic}...")
            yield StepOutput(content=f"Research complete for {topic}: AI automation, Cloud computing")

        def content_planning_step(step_input: StepInput) -> StepOutput:
            research_content = step_input.previous_step_content
            return StepOutput(content=f"Content Plan based on: {research_content}\nWeek 1: AI focus")

        workflow = Workflow(
            name="Streaming Function Workflow",
            storage=workflow_storage,
            steps=[research_step_stream, content_planning_step],
        )

        events = list(workflow.run(message="AI trends in 2024", stream=True))

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Content Plan based on" in completed_events[0].content
