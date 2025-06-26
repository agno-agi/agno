import os

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.v2.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
)
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2 import Workflow
from agno.workflow.v2.condition import Condition
from agno.workflow.v2.parallel import Parallel
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput


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
def researcher_agent():
    """Create a researcher agent."""
    return Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Research the given topic and provide detailed findings.",
        tools=[DuckDuckGoTools()],
        markdown=True,
    )


@pytest.fixture
def summarizer_agent():
    """Create a summarizer agent."""
    return Agent(
        name="Summarizer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Create a clear summary of the research findings.",
        markdown=True,
    )


@pytest.fixture
def fact_checker_agent():
    """Create a fact checker agent."""
    return Agent(
        name="Fact Checker",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Verify facts and check for accuracy in the research.",
        tools=[DuckDuckGoTools()],
        markdown=True,
    )


@pytest.fixture
def hackernews_agent():
    """Create a HackerNews agent."""
    return Agent(
        name="HackerNews Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="Research tech news and trends from Hacker News",
        tools=[HackerNewsTools()],
        markdown=True,
    )


# Function-based steps for testing without API keys
def research_step_function(step_input: StepInput) -> StepOutput:
    """Research function step."""
    topic = step_input.message
    return StepOutput(
        step_name="research_step_function",
        content=f"Research findings for {topic}: Discovered comprehensive information about the topic with various data points and statistics showing 40% growth.",
    )


def summarize_step_function(step_input: StepInput) -> StepOutput:
    """Summarize function step."""
    previous_content = step_input.previous_step_content or ""
    return StepOutput(
        step_name="summarize_step_function",
        content=f"Summary: {previous_content[:100]}... Key insights include data showing significant trends and statistics.",
    )


def fact_check_step_function(step_input: StepInput) -> StepOutput:
    """Fact check function step."""
    previous_content = step_input.previous_step_content or ""
    return StepOutput(
        step_name="fact_check_step_function",
        content=f"Fact Check Results: Verified claims in previous content. Statistics confirmed through multiple sources.",
    )


def tech_research_step_function(step_input: StepInput) -> StepOutput:
    """Tech research function step."""
    topic = step_input.message
    return StepOutput(
        step_name="tech_research_step_function",
        content=f"Tech Research on {topic}: Found trending discussions about AI startups, programming languages, and industry developments.",
    )


def comprehensive_analysis_step_function(step_input: StepInput) -> StepOutput:
    """Comprehensive analysis function step."""
    topic = step_input.message
    return StepOutput(
        step_name="comprehensive_analysis_step_function",
        content=f"Comprehensive Analysis for {topic}: Deep dive analysis with extensive research from multiple sources and cross-referenced data.",
    )


def trend_analysis_step_function(step_input: StepInput) -> StepOutput:
    """Trend analysis function step."""
    previous_content = step_input.previous_step_content or ""
    return StepOutput(
        step_name="trend_analysis_step_function",
        content=f"Trend Analysis: Based on previous research, identified key patterns and emerging trends in the field.",
    )


def write_content_step_function(step_input: StepInput) -> StepOutput:
    """Write content function step."""
    previous_content = step_input.previous_step_content or ""
    return StepOutput(
        step_name="write_content_step_function",
        content=f"Final Article: Based on all research and analysis, here's a comprehensive article covering the key points and insights.",
    )


# Condition evaluator functions
def needs_fact_checking(step_input: StepInput) -> bool:
    """Determine if the research contains claims that need fact-checking."""
    content = step_input.previous_step_content or step_input.message or ""
    fact_indicators = [
        "study shows",
        "research indicates",
        "according to",
        "data shows",
        "survey",
        "report",
        "million",
        "billion",
        "percent",
        "%",
        "increase",
        "decrease",
        "growth",
    ]
    return any(indicator in content.lower() for indicator in fact_indicators)


def is_tech_topic(step_input: StepInput) -> bool:
    """Check if the topic is tech-related."""
    topic = step_input.message or step_input.previous_step_content or ""
    tech_keywords = [
        "ai",
        "machine learning",
        "programming",
        "software",
        "tech",
        "startup",
        "coding",
        "artificial intelligence",
    ]
    return any(keyword in topic.lower() for keyword in tech_keywords)


def needs_comprehensive_research(step_input: StepInput) -> bool:
    """Check if comprehensive research is needed."""
    topic = step_input.message or step_input.previous_step_content or ""
    comprehensive_keywords = [
        "comprehensive",
        "detailed",
        "thorough",
        "in-depth",
        "complete analysis",
        "full report",
        "extensive research",
    ]
    return any(keyword in topic.lower() for keyword in comprehensive_keywords)


def always_true_evaluator(step_input: StepInput) -> bool:
    """Always return True."""
    return True


def always_false_evaluator(step_input: StepInput) -> bool:
    """Always return False."""
    return False


async def async_tech_evaluator(step_input: StepInput) -> bool:
    """Async version of tech topic evaluator."""
    return is_tech_topic(step_input)


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
class TestConditionStepsIntegration:
    """Integration tests for condition steps with real agents."""

    def test_condition_true_single_step_non_streaming(
        self, workflow_storage, researcher_agent, summarizer_agent, fact_checker_agent
    ):
        """Test condition that evaluates to True with single step (non-streaming)."""
        research_step = Step(name="research", agent=researcher_agent)
        summarize_step = Step(name="summarize", agent=summarizer_agent)
        fact_check_step = Step(name="fact_check", agent=fact_checker_agent)

        workflow = Workflow(
            name="Conditional Fact Check Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                summarize_step,
                Condition(
                    name="fact_check_condition",
                    description="Check if fact-checking is needed",
                    evaluator=needs_fact_checking,
                    steps=[fact_check_step],
                ),
            ],
        )

        response = workflow.run(message="Latest statistics show 40% increase in AI adoption")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None

        # The workflow returns a list that contains:
        # [research_output, summarize_output, [fact_check_output]]
        # The condition returns a list, which gets appended to collected_step_outputs
        assert len(response.step_responses) == 3

        # The condition step returns a list, so we need to check it properly
        condition_outputs = response.step_responses[2]
        assert isinstance(condition_outputs, list)
        assert len(condition_outputs) == 1

        # Verify the fact check step was executed within the condition
        fact_check_output = condition_outputs[0]
        assert fact_check_output.step_name == "fact_check"
        assert len(fact_check_output.content) > 0

    def test_condition_false_single_step_non_streaming(
        self, workflow_storage, researcher_agent, summarizer_agent, fact_checker_agent
    ):
        """Test condition that evaluates to False (non-streaming)."""
        research_step = Step(name="research", agent=researcher_agent)
        summarize_step = Step(name="summarize", agent=summarizer_agent)
        fact_check_step = Step(name="fact_check", agent=fact_checker_agent)

        workflow = Workflow(
            name="Conditional Fact Check Workflow",
            storage=workflow_storage,
            steps=[
                research_step,
                summarize_step,
                Condition(
                    name="fact_check_condition",
                    description="Check if fact-checking is needed",
                    evaluator=needs_fact_checking,
                    steps=[fact_check_step],
                ),
            ],
        )

        response = workflow.run(message="General information about cooking recipes")

        assert isinstance(response, WorkflowRunResponse)

        # The step_responses will be empty due to the error
        assert len(response.step_responses) == 0

    def test_condition_with_parallel_steps_streaming(self, workflow_storage, hackernews_agent, researcher_agent):
        """Test condition within parallel steps with streaming."""
        tech_research_step = Step(name="tech_research", agent=hackernews_agent)
        content_step = Step(name="write_content", agent=researcher_agent)

        workflow = Workflow(
            name="Conditional Parallel Workflow",
            storage=workflow_storage,
            steps=[
                Parallel(
                    Condition(
                        name="tech_condition",
                        description="Check if tech research is needed",
                        evaluator=is_tech_topic,
                        steps=[tech_research_step],
                    ),
                    name="conditional_research",
                ),
                content_step,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="Latest AI developments in machine learning", stream=True):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

        # Check for condition events
        condition_started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
        condition_completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

        assert len(condition_started_events) >= 1
        assert len(condition_completed_events) >= 1
        assert condition_started_events[0].condition_result is True

    @pytest.mark.asyncio
    async def test_async_condition_workflow(self, workflow_storage, researcher_agent, hackernews_agent):
        """Test async condition workflow."""
        tech_research_step = Step(name="tech_research", agent=hackernews_agent)
        general_research_step = Step(name="general_research", agent=researcher_agent)

        workflow = Workflow(
            name="Async Conditional Workflow",
            storage=workflow_storage,
            steps=[
                Condition(
                    name="async_tech_condition",
                    description="Async check if tech research is needed",
                    evaluator=async_tech_evaluator,
                    steps=[tech_research_step],
                ),
                general_research_step,
            ],
        )

        response = await workflow.arun(message="AI and machine learning developments")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # condition step + general research
        assert len(response.step_responses) == 2


class TestConditionStepsWithFunctions:
    """Integration tests for condition steps using function executors (no API keys required)."""

    def test_condition_true_single_step_function_non_streaming(self, workflow_storage):
        """Test condition that evaluates to True with function steps (non-streaming)."""
        workflow = Workflow(
            name="Function Conditional Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                summarize_step_function,
                Condition(
                    name="fact_check_condition",
                    description="Check if fact-checking is needed",
                    evaluator=needs_fact_checking,
                    steps=[fact_check_step_function],
                ),
                write_content_step_function,
            ],
        )

        response = workflow.run(message="Study shows 40% increase in renewable energy adoption")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # All steps executed including condition step
        assert len(response.step_responses) == 4

        # Verify condition step was executed - condition returns list
        condition_outputs = response.step_responses[2]
        assert isinstance(condition_outputs, list)
        assert len(condition_outputs) == 1

        fact_check_step = condition_outputs[0]
        assert fact_check_step.step_name == "fact_check_step_function"
        assert "Fact Check Results" in fact_check_step.content

    def test_condition_false_single_step_function_non_streaming(self, workflow_storage):
        """Test condition that evaluates to False with function steps (non-streaming)."""
        workflow = Workflow(
            name="Function Conditional Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                summarize_step_function,
                Condition(
                    name="fact_check_condition",
                    description="Check if fact-checking is needed",
                    evaluator=needs_fact_checking,
                    steps=[fact_check_step_function],
                ),
                write_content_step_function,
            ],
        )

        response = workflow.run(message="General cooking tips and recipes")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # All steps including condition that returns empty list
        assert len(response.step_responses) == 4

        # Verify condition step returned empty list
        condition_outputs = response.step_responses[2]
        assert isinstance(condition_outputs, list)
        assert len(condition_outputs) == 0

    def test_condition_multiple_steps_function_non_streaming(self, workflow_storage):
        """Test condition with multiple steps in condition block."""
        workflow = Workflow(
            name="Multi-Step Condition Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="comprehensive_research_condition",
                    description="Check if comprehensive research is needed",
                    evaluator=needs_comprehensive_research,
                    steps=[
                        comprehensive_analysis_step_function,
                        trend_analysis_step_function,
                        fact_check_step_function,
                    ],
                ),
                write_content_step_function,
            ],
        )

        response = workflow.run(message="Comprehensive analysis of climate change research")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # research + condition + write
        assert len(response.step_responses) == 3

        # Verify all condition steps were executed
        condition_outputs = response.step_responses[1]
        assert isinstance(condition_outputs, list)
        assert len(condition_outputs) == 3

        condition_step_1 = condition_outputs[0]
        condition_step_2 = condition_outputs[1]
        condition_step_3 = condition_outputs[2]

        assert condition_step_1.step_name == "comprehensive_analysis_step_function"
        assert condition_step_2.step_name == "trend_analysis_step_function"
        assert condition_step_3.step_name == "fact_check_step_function"

    def test_condition_with_parallel_steps_function_streaming(self, workflow_storage):
        """Test condition within parallel steps with function executors and streaming."""
        workflow = Workflow(
            name="Function Conditional Parallel Workflow",
            storage=workflow_storage,
            steps=[
                Parallel(
                    Condition(
                        name="tech_condition",
                        description="Check if tech research is needed",
                        evaluator=is_tech_topic,
                        steps=[tech_research_step_function],
                    ),
                    Condition(
                        name="comprehensive_condition",
                        description="Check if comprehensive research is needed",
                        evaluator=needs_comprehensive_research,
                        steps=[comprehensive_analysis_step_function],
                    ),
                    name="conditional_research",
                ),
                write_content_step_function,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="Comprehensive AI research and machine learning analysis", stream=True):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

        # Check for condition events
        condition_started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
        condition_completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

        # Should have both conditions triggered
        assert len(condition_started_events) == 2
        assert len(condition_completed_events) == 2

        # Both conditions should evaluate to True
        for event in condition_started_events:
            assert event.condition_result is True

    def test_condition_boolean_evaluator(self, workflow_storage):
        """Test condition with boolean evaluator (not function)."""
        workflow = Workflow(
            name="Boolean Condition Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="always_true_condition",
                    description="Always execute this condition",
                    evaluator=True,  # Boolean instead of function
                    steps=[fact_check_step_function],
                ),
                Condition(
                    name="always_false_condition",
                    description="Never execute this condition",
                    evaluator=False,  # Boolean instead of function
                    steps=[trend_analysis_step_function],
                ),
                write_content_step_function,
            ],
        )

        response = workflow.run(message="Any topic")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # research + true_condition + false_condition + write
        assert len(response.step_responses) == 4

        # Verify only the True condition step was executed
        true_condition_outputs = response.step_responses[1]
        assert isinstance(true_condition_outputs, list)
        assert len(true_condition_outputs) == 1
        assert true_condition_outputs[0].step_name == "fact_check_step_function"

        # Verify false condition returned empty list
        false_condition_outputs = response.step_responses[2]
        assert isinstance(false_condition_outputs, list)
        assert len(false_condition_outputs) == 0

    @pytest.mark.asyncio
    async def test_async_condition_function_workflow(self, workflow_storage):
        """Test async condition workflow with function executors."""
        workflow = Workflow(
            name="Async Function Conditional Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="async_tech_condition",
                    description="Async check if tech research is needed",
                    evaluator=async_tech_evaluator,
                    steps=[tech_research_step_function],
                ),
                write_content_step_function,
            ],
        )

        response = await workflow.arun(message="Programming and software development trends")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # research + condition + write
        assert len(response.step_responses) == 3

    @pytest.mark.asyncio
    async def test_async_condition_function_streaming(self, workflow_storage):
        """Test async condition workflow with function executors and streaming."""
        workflow = Workflow(
            name="Async Function Conditional Streaming Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="async_tech_condition",
                    description="Async check if tech research is needed",
                    evaluator=async_tech_evaluator,
                    steps=[tech_research_step_function, fact_check_step_function],
                ),
                write_content_step_function,
            ],
        )

        # Collect async streaming events
        events = []
        async for event in await workflow.arun(message="AI and software engineering", stream=True):
            events.append(event)

        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1

        # Check for condition events
        condition_started_events = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
        condition_completed_events = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

        assert len(condition_started_events) == 1
        assert len(condition_completed_events) == 1
        assert condition_started_events[0].condition_result is True

    def test_condition_error_handling(self, workflow_storage):
        """Test condition error handling when evaluator fails."""

        def failing_evaluator(step_input: StepInput) -> bool:
            """Evaluator that always raises an exception."""
            raise ValueError("Evaluator failed!")

        workflow = Workflow(
            name="Error Handling Condition Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="failing_condition",
                    description="Condition that fails",
                    evaluator=failing_evaluator,
                    steps=[fact_check_step_function],
                ),
                write_content_step_function,
            ],
        )

        # The workflow should fail due to the unhandled exception in condition evaluator
        response = workflow.run(message="Any topic")

        assert isinstance(response, WorkflowRunResponse)
        # The workflow should have failed, so check for error status
        from agno.run.base import RunStatus

        assert response.status == RunStatus.error
        assert "Evaluator failed!" in response.content

    def test_nested_conditions(self, workflow_storage):
        """Test nested conditions within conditions."""

        def inner_evaluator(step_input: StepInput) -> bool:
            """Inner condition evaluator."""
            return "detailed" in (step_input.message or "").lower()

        workflow = Workflow(
            name="Nested Condition Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="outer_condition",
                    description="Outer condition",
                    evaluator=needs_comprehensive_research,
                    steps=[
                        comprehensive_analysis_step_function,
                        Condition(
                            name="inner_condition",
                            description="Inner condition",
                            evaluator=inner_evaluator,
                            steps=[trend_analysis_step_function],
                        ),
                    ],
                ),
                write_content_step_function,
            ],
        )

        response = workflow.run(message="Comprehensive and detailed analysis needed")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # research + outer_condition + write
        assert len(response.step_responses) == 3

        # Verify nested condition step was executed
        outer_condition_outputs = response.step_responses[1]
        assert isinstance(outer_condition_outputs, list)
        # Should have: comprehensive_analysis + [trend_analysis] (inner condition output)
        assert len(outer_condition_outputs) == 2

        # First output is comprehensive_analysis
        assert outer_condition_outputs[0].step_name == "comprehensive_analysis_step_function"

        # Second output is from the inner condition
        # Since the inner condition's execute() method returns a list, it gets flattened
        # into the outer condition's results. So the trend_analysis step becomes a direct
        # StepOutput in the outer condition results
        inner_condition_output = outer_condition_outputs[1]
        assert isinstance(inner_condition_output, StepOutput)
        assert inner_condition_output.step_name == "trend_analysis_step_function"

    def test_condition_step_chaining(self, workflow_storage):
        """Test that steps within condition receive previous step content."""

        def step_access_checker(step_input: StepInput) -> StepOutput:
            """Step that checks if it has access to previous step content."""
            previous_content = step_input.previous_step_content or ""
            has_previous = len(previous_content) > 0

            return StepOutput(
                step_name="step_access_checker",
                content=f"Has previous content: {has_previous}. Previous content preview: {previous_content[:50]}...",
                success=True,
            )

        workflow = Workflow(
            name="Condition Step Chaining Workflow",
            storage=workflow_storage,
            steps=[
                research_step_function,
                Condition(
                    name="chaining_condition",
                    description="Test step chaining in condition",
                    evaluator=always_true_evaluator,
                    steps=[
                        fact_check_step_function,
                        step_access_checker,  # Should receive fact_check output
                    ],
                ),
            ],
        )

        response = workflow.run(message="Test step chaining")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        # research + condition
        assert len(response.step_responses) == 2

        # Verify step chaining worked
        condition_outputs = response.step_responses[1]
        assert isinstance(condition_outputs, list)
        assert len(condition_outputs) == 2

        access_checker_step = condition_outputs[1]
        assert "Has previous content: True" in access_checker_step.content
