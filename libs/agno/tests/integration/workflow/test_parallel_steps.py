import asyncio
import os
from typing import List

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.googlesearch import GoogleSearchTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2 import Workflow
from agno.workflow.v2.parallel import Parallel
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput
from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse


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
def researcher_agent():
    """Create a researcher agent with tools."""
    return Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Senior Research Analyst",
        goal="Gather comprehensive information from multiple sources",
        tools=[HackerNewsTools(), GoogleSearchTools()],
        instructions="You are a research specialist. Research the given topic thoroughly.",
        markdown=True,
    )


@pytest.fixture
def writer_agent():
    """Create a writer agent."""
    return Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Content Writer",
        goal="Create engaging and informative content",
        instructions="You are a content writer. Create engaging content based on research.",
        markdown=True,
    )


@pytest.fixture
def reviewer_agent():
    """Create a reviewer agent."""
    return Agent(
        name="Reviewer",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Content Reviewer",
        goal="Review and improve content quality",
        instructions="You are a content reviewer. Review and improve content quality.",
        markdown=True,
    )


# Function-based steps for testing without API keys
def research_hackernews_step(step_input: StepInput) -> StepOutput:
    """Simple HackerNews research function step."""
    topic = step_input.message
    return StepOutput(
        content=f"HackerNews Research for {topic}: Found 5 trending stories about AI developments, including discussions on GPT-4, machine learning frameworks, and startup funding."
    )


def research_web_step(step_input: StepInput) -> StepOutput:
    """Simple web research function step."""
    topic = step_input.message
    return StepOutput(
        content=f"Web Research for {topic}: Discovered recent articles about neural networks, AI ethics, and industry partnerships from major tech companies."
    )


def write_article_step(step_input: StepInput) -> StepOutput:
    """Simple article writing function step."""
    research_content = step_input.get_all_previous_content()
    return StepOutput(
        content=f"Article: Based on the research findings, here's a comprehensive overview of AI developments. Research summary: {research_content[:200]}..."
    )


def review_article_step(step_input: StepInput) -> StepOutput:
    """Simple article review function step."""
    article_content = step_input.previous_step_content or "No article content"
    return StepOutput(
        content=f"Review: The article provides good coverage of AI developments. Suggestions: Add more technical details. Content length: {len(article_content)} characters."
    )


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
class TestParallelStepsIntegration:
    """Integration tests for Parallel steps with real agents."""

    def test_basic_parallel_workflow_non_streaming(self, workflow_storage, researcher_agent, writer_agent, reviewer_agent):
        """Test basic parallel workflow without streaming."""
        # Create individual steps
        research_hn_step = Step(
            name="Research HackerNews", agent=researcher_agent)
        research_web_step = Step(name="Research Web", agent=researcher_agent)
        write_step = Step(name="Write Article", agent=writer_agent)
        review_step = Step(name="Review Article", agent=reviewer_agent)

        workflow = Workflow(
            name="Content Creation Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(research_hn_step, research_web_step,
                         name="Research Phase"),
                write_step,
                review_step,
            ],
        )

        response = workflow.run(
            message="Write about the latest AI developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.content) > 100
        assert "AI" in response.content or "artificial intelligence" in response.content.lower()

        # Verify we have outputs from all steps (3 steps: Parallel, Write, Review)
        assert len(response.step_responses) == 3

        # Parallel step returns single aggregated StepOutput, not a list
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert parallel_output.step_name == "Research Phase"
        # Verify it contains content from both parallel steps
        assert "Research HackerNews" in parallel_output.content or "Research Web" in parallel_output.content

    def test_basic_parallel_workflow_streaming(self, workflow_storage, researcher_agent, writer_agent, reviewer_agent):
        """Test basic parallel workflow with streaming."""
        # Create individual steps
        research_hn_step = Step(
            name="Research HackerNews", agent=researcher_agent)
        research_web_step = Step(name="Research Web", agent=researcher_agent)
        write_step = Step(name="Write Article", agent=writer_agent)
        review_step = Step(name="Review Article", agent=reviewer_agent)

        workflow = Workflow(
            name="Content Creation Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(research_hn_step, research_web_step,
                         name="Research Phase"),
                write_step,
                review_step,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="Write about the latest AI developments", stream=True):
            events.append(event)

        # Verify we received streaming events
        assert len(events) > 0

        # Check for final completion event
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert len(completed_events[0].content) > 100
        assert "AI" in completed_events[0].content or "artificial intelligence" in completed_events[0].content.lower(
        )

    @pytest.mark.asyncio
    async def test_async_parallel_workflow(self, workflow_storage, researcher_agent, writer_agent, reviewer_agent):
        """Test async parallel workflow execution."""
        # Create individual steps
        research_hn_step = Step(
            name="Research HackerNews", agent=researcher_agent)
        research_web_step = Step(name="Research Web", agent=researcher_agent)
        write_step = Step(name="Write Article", agent=writer_agent)

        workflow = Workflow(
            name="Async Content Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(research_hn_step, research_web_step,
                         name="Research Phase"),
                write_step,
            ],
        )

        response = await workflow.arun(message="Write about machine learning trends")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.content) > 50

        # Parallel step returns single aggregated StepOutput, not a list
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert parallel_output.step_name == "Research Phase"

    @pytest.mark.asyncio
    async def test_async_parallel_workflow_streaming(self, workflow_storage, researcher_agent, writer_agent):
        """Test async parallel workflow with streaming."""
        # Create individual steps
        research_hn_step = Step(
            name="Research HackerNews", agent=researcher_agent)
        research_web_step = Step(name="Research Web", agent=researcher_agent)
        write_step = Step(name="Write Article", agent=writer_agent)

        workflow = Workflow(
            name="Async Streaming Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(research_hn_step, research_web_step,
                         name="Research Phase"),
                write_step,
            ],
        )

        # Collect async streaming events - FIXED: use await to get async iterator
        events = []
        async for event in await workflow.arun(message="Write about neural networks", stream=True):
            events.append(event)

        # Verify streaming and parallel execution
        assert len(events) > 0
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert len(completed_events[0].content) > 50


class TestParallelStepsWithFunctions:
    """Integration tests for Parallel steps using function executors (no API keys required)."""

    def test_basic_function_parallel_non_streaming(self, workflow_storage):
        """Test basic parallel workflow with function executors."""
        workflow = Workflow(
            name="Function-based Content Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_hackernews_step,
                    research_web_step,
                    name="Research Phase"
                ),
                write_article_step,
                review_article_step,
            ],
        )

        response = workflow.run(message="AI developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.content) > 50
        assert "Review:" in response.content

        # Verify parallel execution structure - 3 steps total
        assert len(response.step_responses) == 3

        # Parallel step returns single aggregated StepOutput, not a list
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert parallel_output.step_name == "Research Phase"

        # Verify aggregated content contains both parallel step results
        assert "HackerNews Research" in parallel_output.content
        assert "Web Research" in parallel_output.content
        assert "trending stories" in parallel_output.content
        assert "neural networks" in parallel_output.content

    def test_basic_function_parallel_streaming(self, workflow_storage):
        """Test basic parallel workflow with function executors and streaming."""
        workflow = Workflow(
            name="Function-based Streaming Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_hackernews_step,
                    research_web_step,
                    name="Research Phase"
                ),
                write_article_step,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="AI developments", stream=True):
            events.append(event)

        # Verify streaming events were generated
        assert len(events) > 0

        # Check for final completion event
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Article:" in completed_events[0].content

    @pytest.mark.asyncio
    async def test_async_function_parallel_non_streaming(self, workflow_storage):
        """Test async parallel workflow with function executors."""
        workflow = Workflow(
            name="Async Function Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_hackernews_step,
                    research_web_step,
                    name="Research Phase"
                ),
                write_article_step,
            ],
        )

        response = await workflow.arun(message="AI developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert "Article:" in response.content

        # Parallel step returns single aggregated StepOutput, not a list
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert parallel_output.step_name == "Research Phase"

    @pytest.mark.asyncio
    async def test_async_function_parallel_streaming(self, workflow_storage):
        """Test async parallel workflow with function executors and streaming."""
        workflow = Workflow(
            name="Async Function Streaming Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_hackernews_step,
                    research_web_step,
                    name="Research Phase"
                ),
                write_article_step,
            ],
        )

        # Collect async streaming events - FIXED: use await to get async iterator
        events = []
        async for event in await workflow.arun(message="AI developments", stream=True):
            events.append(event)

        # Verify streaming and parallel execution
        assert len(events) > 0
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Article:" in completed_events[0].content

    def test_nested_parallel_steps(self, workflow_storage):
        """Test workflow with nested parallel steps."""
        def research_step_1(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Research 1: Found data about AI trends")

        def research_step_2(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Research 2: Found data about ML algorithms")

        def analysis_step_1(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Analysis 1: Processed research findings")

        def analysis_step_2(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Analysis 2: Generated insights")

        workflow = Workflow(
            name="Nested Parallel Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_step_1,
                    research_step_2,
                    name="Research Phase"
                ),
                Parallel(
                    analysis_step_1,
                    analysis_step_2,
                    name="Analysis Phase"
                ),
                write_article_step,
            ],
        )

        response = workflow.run(message="AI and ML topics")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None

        # Should have 3 step responses: 2 parallel + 1 write
        assert len(response.step_responses) == 3

        # Each parallel step returns single aggregated StepOutput, not a list
        # Research parallel
        assert isinstance(response.step_responses[0], StepOutput)
        # Analysis parallel
        assert isinstance(response.step_responses[1], StepOutput)
        assert isinstance(response.step_responses[2], StepOutput)  # Write step

        # Verify names
        assert response.step_responses[0].step_name == "Research Phase"
        assert response.step_responses[1].step_name == "Analysis Phase"

    def test_parallel_with_mixed_step_types(self, workflow_storage):
        """Test parallel execution with mixed step types (functions and Step objects)."""
        # Create a Step object
        research_step_obj = Step(
            name="Research Step Object",
            executor=research_hackernews_step
        )

        workflow = Workflow(
            name="Mixed Parallel Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_step_obj,  # Step object
                    research_web_step,  # Function
                    name="Mixed Research Phase"
                ),
                write_article_step,
            ],
        )

        response = workflow.run(message="AI developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None

        # Parallel step returns single aggregated StepOutput, not a list
        parallel_output = response.step_responses[0]
        assert isinstance(parallel_output, StepOutput)
        assert parallel_output.step_name == "Mixed Research Phase"

        # Verify aggregated content contains both step outputs
        assert "HackerNews Research" in parallel_output.content
        assert "Web Research" in parallel_output.content

    def test_nested_parallel_streaming(self, workflow_storage):
        """Test nested parallel steps with streaming."""
        def research_step_1(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Research 1: Found data about AI trends")

        def research_step_2(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Research 2: Found data about ML algorithms")

        def analysis_step_1(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Analysis 1: Processed research findings")

        def analysis_step_2(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Analysis 2: Generated insights")

        workflow = Workflow(
            name="Nested Parallel Streaming Pipeline",
            storage=workflow_storage,
            steps=[
                Parallel(
                    research_step_1,
                    research_step_2,
                    name="Research Phase"
                ),
                Parallel(
                    analysis_step_1,
                    analysis_step_2,
                    name="Analysis Phase"
                ),
                write_article_step,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="AI and ML topics", stream=True):
            events.append(event)

        # Verify streaming events were generated
        assert len(events) > 0

        # Check for final completion event
        completed_events = [e for e in events if isinstance(
            e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Article:" in completed_events[0].content
