"""Integration tests for Workflow v2 Loop functionality"""

import asyncio
import os
from typing import List

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.v2.workflow import (
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
)
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2 import Loop, Parallel, Step, StepInput, StepOutput, Workflow


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
def research_agent():
    """Create a real research agent for testing."""
    return Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Research specialist",
        tools=[HackerNewsTools(), DuckDuckGoTools()],
        instructions="You are a research specialist. Research the given topic thoroughly.",
        markdown=True,
    )


@pytest.fixture
def analysis_agent():
    """Create a real analysis agent for testing."""
    return Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Data analyst",
        instructions="You are a data analyst. Analyze and summarize research findings.",
        markdown=True,
    )


@pytest.fixture
def content_agent():
    """Create a real content agent for testing."""
    return Agent(
        name="Content Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        role="Content creator",
        instructions="You are a content creator. Create engaging content based on research.",
        markdown=True,
    )


# End condition functions
def research_evaluator(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if research results are sufficient
    Returns True to break the loop, False to continue
    """
    if not outputs:
        return False

    # Check if any output contains substantial content
    for output in outputs:
        if output.content and len(output.content) > 200:
            print(f"✅ Research evaluation passed - found substantial content ({len(output.content)} chars)")
            return True

    print("❌ Research evaluation failed - need more substantial research")
    return False


def comprehensive_research_evaluator(outputs: List[StepOutput]) -> bool:
    """
    More comprehensive evaluator for parallel step testing
    """
    if not outputs:
        return False

    # Calculate total content length from all outputs
    total_content_length = sum(len(output.content or "") for output in outputs)

    # Check if we have substantial content (more than 500 chars total)
    if total_content_length > 500:
        print(f"✅ Research evaluation passed - found substantial content ({total_content_length} chars total)")
        return True

    print(f"❌ Research evaluation failed - need more substantial research (current: {total_content_length} chars)")
    return False


# Function-based step executors for testing without API keys
def simple_research_step(step_input: StepInput) -> StepOutput:
    """Simple research function step."""
    topic = step_input.message
    iteration = getattr(step_input, "iteration", 1)
    return StepOutput(content=f"Research iteration {iteration} for {topic}: Found new insights about AI trends")


def simple_analysis_step(step_input: StepInput) -> StepOutput:
    """Simple analysis function step."""
    prev_content = step_input.previous_step_content or "no previous content"
    iteration = getattr(step_input, "iteration", 1)
    return StepOutput(content=f"Analysis iteration {iteration}: Processed {len(prev_content)} chars of research data")


def simple_content_step(step_input: StepInput) -> StepOutput:
    """Simple content creation function step."""
    prev_content = step_input.previous_step_content or "no previous content"
    return StepOutput(content=f"Final content based on research: {prev_content[:100]}...")


def simple_evaluator(outputs: List[StepOutput]) -> bool:
    """Simple evaluator that stops after 2 iterations."""
    return len(outputs) >= 2


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
class TestLoopStepsIntegration:
    """Integration tests for Loop functionality using real agents."""

    def test_basic_loop_workflow_non_streaming(self, research_agent, content_agent, workflow_storage):
        """Test basic loop workflow like cookbook example - non-streaming."""
        # Create research steps
        research_hackernews_step = Step(
            name="Research HackerNews",
            agent=research_agent,
            description="Research trending topics on HackerNews",
        )

        research_web_step = Step(
            name="Research Web",
            agent=research_agent,
            description="Research additional information from web sources",
        )

        content_step = Step(
            name="Create Content",
            agent=content_agent,
            description="Create content based on research findings",
        )

        # Create workflow with loop - matches cookbook exactly
        workflow = Workflow(
            name="Research and Content Workflow",
            description="Research topics in a loop until conditions are met, then create content",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Research Loop",
                    steps=[research_hackernews_step, research_web_step],
                    end_condition=research_evaluator,
                    max_iterations=3,
                ),
                content_step,
            ],
        )

        response = workflow.run(message="Research the latest trends in AI and machine learning, then create a summary")

        # Verify response structure
        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert response.workflow_name == "Research and Content Workflow"
        assert len(response.step_responses) == 2  # Loop + Content step

        # Verify actual content was generated
        assert len(response.content) > 100
        final_content = response.content.lower()
        assert "ai" in final_content or "machine learning" in final_content

    def test_basic_loop_workflow_streaming(self, research_agent, content_agent, workflow_storage):
        """Test basic loop workflow with streaming."""
        research_hackernews_step = Step(
            name="Research HackerNews",
            agent=research_agent,
            description="Research trending topics on HackerNews",
        )

        research_web_step = Step(
            name="Research Web",
            agent=research_agent,
            description="Research additional information from web sources",
        )

        content_step = Step(
            name="Create Content",
            agent=content_agent,
            description="Create content based on research findings",
        )

        workflow = Workflow(
            name="Research and Content Workflow",
            description="Research topics in a loop until conditions are met, then create content",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Research Loop",
                    steps=[research_hackernews_step, research_web_step],
                    end_condition=research_evaluator,
                    max_iterations=3,
                ),
                content_step,
            ],
        )

        events = list(
            workflow.run(
                message="Research the latest trends in AI and machine learning, then create a summary",
                stream=True,
                stream_intermediate_steps=True,
            )
        )

        # Verify we get events and final completion
        assert len(events) > 0

        # Check for loop-specific events
        loop_started_events = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
        loop_completed_events = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
        iteration_started_events = [e for e in events if isinstance(e, LoopIterationStartedEvent)]
        iteration_completed_events = [e for e in events if isinstance(e, LoopIterationCompletedEvent)]

        assert len(loop_started_events) >= 1
        assert len(loop_completed_events) >= 1
        assert len(iteration_started_events) >= 1
        assert len(iteration_completed_events) >= 1

        # Check final completion
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert len(completed_events[0].content) > 100

    def test_loop_with_parallel_steps_non_streaming(
        self, research_agent, analysis_agent, content_agent, workflow_storage
    ):
        """Test loop with parallel steps - matches cookbook example."""
        # Create research steps
        research_hackernews_step = Step(
            name="Research HackerNews",
            agent=research_agent,
            description="Research trending topics on HackerNews",
        )

        research_web_step = Step(
            name="Research Web",
            agent=research_agent,
            description="Research additional information from web sources",
        )

        # Create analysis steps
        trend_analysis_step = Step(
            name="Trend Analysis",
            agent=analysis_agent,
            description="Analyze trending patterns in the research",
        )

        sentiment_analysis_step = Step(
            name="Sentiment Analysis",
            agent=analysis_agent,
            description="Analyze sentiment and opinions from the research",
        )

        content_step = Step(
            name="Create Content",
            agent=content_agent,
            description="Create content based on research findings",
        )

        # Create workflow with loop containing parallel steps - matches cookbook exactly
        workflow = Workflow(
            name="Advanced Research and Content Workflow",
            description="Research topics with parallel execution in a loop until conditions are met, then create content",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Research Loop with Parallel Execution",
                    steps=[
                        Parallel(
                            research_hackernews_step,
                            research_web_step,
                            trend_analysis_step,
                            name="Parallel Research & Analysis",
                            description="Execute research and analysis in parallel for efficiency",
                        ),
                        sentiment_analysis_step,
                    ],
                    end_condition=comprehensive_research_evaluator,
                    max_iterations=3,
                ),
                content_step,
            ],
        )

        response = workflow.run(message="Research the latest trends in AI and machine learning, then create a summary")

        # Verify response structure
        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 2  # Loop + Content step

        # Verify actual content was generated
        assert len(response.content) > 100

    def test_loop_with_parallel_steps_streaming(self, research_agent, analysis_agent, content_agent, workflow_storage):
        """Test loop with parallel steps and streaming."""
        research_hackernews_step = Step(
            name="Research HackerNews",
            agent=research_agent,
            description="Research trending topics on HackerNews",
        )

        research_web_step = Step(
            name="Research Web",
            agent=research_agent,
            description="Research additional information from web sources",
        )

        trend_analysis_step = Step(
            name="Trend Analysis",
            agent=analysis_agent,
            description="Analyze trending patterns in the research",
        )

        sentiment_analysis_step = Step(
            name="Sentiment Analysis",
            agent=analysis_agent,
            description="Analyze sentiment and opinions from the research",
        )

        content_step = Step(
            name="Create Content",
            agent=content_agent,
            description="Create content based on research findings",
        )

        workflow = Workflow(
            name="Advanced Research and Content Workflow",
            description="Research topics with parallel execution in a loop until conditions are met, then create content",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Research Loop with Parallel Execution",
                    steps=[
                        Parallel(
                            research_hackernews_step,
                            research_web_step,
                            trend_analysis_step,
                            name="Parallel Research & Analysis",
                            description="Execute research and analysis in parallel for efficiency",
                        ),
                        sentiment_analysis_step,
                    ],
                    end_condition=comprehensive_research_evaluator,
                    max_iterations=3,
                ),
                content_step,
            ],
        )

        events = list(
            workflow.run(
                message="Research the latest trends in AI and machine learning, then create a summary",
                stream=True,
                stream_intermediate_steps=True,
            )
        )

        # Verify we get events and final completion
        assert len(events) > 0

        # Check for loop and parallel events
        loop_events = [e for e in events if isinstance(e, (LoopExecutionStartedEvent, LoopExecutionCompletedEvent))]
        assert len(loop_events) >= 2  # At least started and completed

        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

    @pytest.mark.asyncio
    async def test_async_loop_workflow_non_streaming(self, research_agent, content_agent, workflow_storage):
        """Test async loop workflow."""
        research_step = Step(
            name="Research Step",
            agent=research_agent,
            description="Research the given topic",
        )

        content_step = Step(
            name="Create Content",
            agent=content_agent,
            description="Create content based on research findings",
        )

        workflow = Workflow(
            name="Async Research Loop Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Async Research Loop",
                    steps=[research_step],
                    end_condition=research_evaluator,
                    max_iterations=2,
                ),
                content_step,
            ],
        )

        response = await workflow.arun(message="Research AI trends")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.step_responses) == 2
        assert len(response.content) > 50

    @pytest.mark.asyncio
    async def test_async_loop_workflow_streaming(self, research_agent, content_agent, workflow_storage):
        """Test async loop workflow with streaming."""
        research_step = Step(
            name="Research Step",
            agent=research_agent,
            description="Research the given topic",
        )

        content_step = Step(
            name="Create Content",
            agent=content_agent,
            description="Create content based on research findings",
        )

        workflow = Workflow(
            name="Async Research Loop Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Async Research Loop",
                    steps=[research_step],
                    end_condition=research_evaluator,
                    max_iterations=2,
                ),
                content_step,
            ],
        )

        events = []
        async for event in await workflow.arun(
            message="Research AI trends", stream=True, stream_intermediate_steps=True
        ):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1


class TestLoopStepsWithoutAPIKey:
    """Tests that don't require API key - using only function executors."""

    def test_basic_function_loop_non_streaming(self, workflow_storage):
        """Test basic loop with function executors - no API calls."""
        workflow = Workflow(
            name="Function Loop Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Simple Research Loop",
                    steps=[simple_research_step, simple_analysis_step],
                    end_condition=simple_evaluator,
                    max_iterations=3,
                ),
                simple_content_step,
            ],
        )

        response = workflow.run(message="Test topic")

        assert isinstance(response, WorkflowRunResponse)
        # The final content will be from the last step (simple_content_step)
        # which processes the loop results
        assert "Final content based on research" in response.content
        assert len(response.step_responses) == 2  # Loop + Content step

        # Check that loop executed by examining step_responses
        loop_outputs = response.step_responses[0]  # First step is the Loop
        assert isinstance(loop_outputs, list)
        # Should have results from 2 iterations (simple_evaluator stops after 2)
        assert len(loop_outputs) >= 2

        # Verify loop outputs contain expected content
        research_outputs = [output for output in loop_outputs if "Research iteration" in output.content]
        analysis_outputs = [output for output in loop_outputs if "Analysis iteration" in output.content]
        assert len(research_outputs) >= 1  # At least one research step
        assert len(analysis_outputs) >= 1  # At least one analysis step

    def test_basic_function_loop_streaming(self, workflow_storage):
        """Test basic loop with function executors and streaming - no API calls."""
        workflow = Workflow(
            name="Function Loop Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Simple Research Loop",
                    steps=[simple_research_step, simple_analysis_step],
                    end_condition=simple_evaluator,
                    max_iterations=3,
                ),
                simple_content_step,
            ],
        )

        events = list(workflow.run(message="Test topic", stream=True))

        assert len(events) > 0

        # Check for loop events
        loop_started_events = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
        loop_completed_events = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]

        assert len(loop_started_events) >= 1
        assert len(loop_completed_events) >= 1

        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Final content based on research" in completed_events[0].content

    def test_loop_early_termination(self, workflow_storage):
        """Test that loop terminates early when end condition is met."""

        def early_termination_evaluator(outputs: List[StepOutput]) -> bool:
            """Evaluator that returns True after first iteration."""
            return len(outputs) >= 1

        workflow = Workflow(
            name="Early Termination Test Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Early Termination Loop",
                    steps=[simple_research_step],
                    end_condition=early_termination_evaluator,
                    max_iterations=5,  # Set high, but should stop after 1
                ),
            ],
        )

        response = workflow.run(message="Test topic")

        assert isinstance(response, WorkflowRunResponse)
        # Should contain content from exactly 1 iteration
        assert response.content.count("Research iteration 1") == 1
        assert "Research iteration 2" not in response.content

    @pytest.mark.asyncio
    async def test_async_function_loop_non_streaming(self, workflow_storage):
        """Test async loop with async function executors."""

        async def async_research_step(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)
            topic = step_input.message
            return StepOutput(content=f"Async research for {topic}: AI insights")

        async def async_evaluator(outputs: List[StepOutput]) -> bool:
            await asyncio.sleep(0.01)
            return len(outputs) >= 1

        workflow = Workflow(
            name="Async Function Loop Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Async Research Loop",
                    steps=[async_research_step],
                    end_condition=async_evaluator,
                    max_iterations=2,
                ),
            ],
        )

        response = await workflow.arun(message="Test topic")

        assert isinstance(response, WorkflowRunResponse)
        assert "Async research for Test topic" in response.content

    @pytest.mark.asyncio
    async def test_async_function_loop_streaming(self, workflow_storage):
        """Test async loop with async function executors and streaming."""

        async def async_research_step(step_input: StepInput) -> StepOutput:
            await asyncio.sleep(0.01)
            topic = step_input.message
            return StepOutput(content=f"Async research for {topic}: AI insights")

        async def async_evaluator(outputs: List[StepOutput]) -> bool:
            await asyncio.sleep(0.01)
            return len(outputs) >= 1

        workflow = Workflow(
            name="Async Function Loop Workflow",
            storage=workflow_storage,
            steps=[
                Loop(
                    name="Async Research Loop",
                    steps=[async_research_step],
                    end_condition=async_evaluator,
                    max_iterations=2,
                ),
            ],
        )

        events = []
        async for event in await workflow.arun(message="Test topic", stream=True):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Async research for Test topic" in completed_events[0].content
