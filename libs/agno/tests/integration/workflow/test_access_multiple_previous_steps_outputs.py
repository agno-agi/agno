import os
from typing import List, Optional

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2 import Workflow
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
def hackernews_agent():
    """Create a HackerNews research agent."""
    return Agent(
        name="HackerNews Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a researcher specializing in finding the latest tech news and discussions from Hacker News. Focus on startup trends, programming topics, and tech industry insights.",
        tools=[HackerNewsTools()],
        markdown=True,
    )


@pytest.fixture
def web_agent():
    """Create a web research agent."""
    return Agent(
        name="Web Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a comprehensive web researcher. Search across multiple sources including news sites, blogs, and official documentation to gather detailed information.",
        tools=[DuckDuckGoTools()],
        markdown=True,
    )


@pytest.fixture
def reasoning_agent():
    """Create a reasoning agent."""
    return Agent(
        name="Reasoning Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are an expert analyst who creates comprehensive reports by analyzing and synthesizing information from multiple sources. Create well-structured, insightful reports.",
        markdown=True,
    )


# Function-based steps for testing without API keys
def hackernews_research_step(step_input: StepInput) -> StepOutput:
    """Simple HackerNews research function step."""
    topic = step_input.message
    return StepOutput(
        step_name="hackernews_research_step",  # Use function name
        content=f"HackerNews Research on {topic}: Found trending discussions about AI startups, new programming languages, and tech industry layoffs. Key insights include growing interest in AI tools and developer productivity.",
    )


def web_research_step(step_input: StepInput) -> StepOutput:
    """Simple web research function step."""
    topic = step_input.message
    return StepOutput(
        step_name="web_research_step",  # Use function name
        content=f"Web Research on {topic}: Discovered comprehensive articles about machine learning breakthroughs, industry partnerships, and regulatory developments. Major tech companies are investing heavily in AI infrastructure.",
    )


def data_analysis_step(step_input: StepInput) -> StepOutput:
    """Data analysis step that processes previous research."""
    topic = step_input.message
    return StepOutput(
        step_name="data_analysis_step",  # Use function name
        content=f"Data Analysis for {topic}: Statistical trends show 40% increase in AI adoption across industries. Market size projected to reach $190B by 2025.",
    )


def create_comprehensive_report(step_input: StepInput) -> StepOutput:
    """
    Custom function that creates a report using data from multiple previous steps.
    This function has access to ALL previous step outputs and the original workflow message.
    """
    # Access original workflow input
    original_topic = step_input.workflow_message or step_input.message or ""

    # Access specific step outputs by name (use function names, not StepOutput.step_name)
    hackernews_data = step_input.get_step_content("hackernews_research_step") or ""
    web_data = step_input.get_step_content("web_research_step") or ""
    analysis_data = step_input.get_step_content("data_analysis_step") or ""

    # Or access ALL previous content
    all_research = step_input.get_all_previous_content()

    # Verify we can access specific steps
    hackernews_step_output = step_input.get_step_output("hackernews_research_step")
    web_step_output = step_input.get_step_output("web_research_step")

    # Create a comprehensive report combining all sources
    report = f"""# Comprehensive Research Report: {original_topic}

## Executive Summary
Based on research from HackerNews and web sources, here's a comprehensive analysis of {original_topic}.

## HackerNews Insights
{hackernews_data[:200] if hackernews_data else "No HackerNews data available"}...

## Web Research Findings  
{web_data[:200] if web_data else "No web data available"}...

## Data Analysis
{analysis_data[:200] if analysis_data else "No analysis data available"}...

## All Previous Content Summary
Total content length: {len(all_research)} characters

## Step Access Verification
- HackerNews step found: {"Yes" if hackernews_step_output else "No"}
- Web step found: {"Yes" if web_step_output else "No"}
- Available step names: {list(step_input.previous_steps_outputs.keys()) if step_input.previous_steps_outputs else "None"}
"""

    return StepOutput(
        step_name="create_comprehensive_report",  # Use function name
        content=report.strip(),
        success=True,
    )


def final_reasoning_step(step_input: StepInput) -> StepOutput:
    """Final reasoning step that builds on the comprehensive report."""
    previous_content = step_input.previous_step_content or ""

    reasoning = f"""# Final Analysis and Recommendations

## Based on Comprehensive Research
{previous_content[:300] if previous_content else "No previous content"}...

## Key Recommendations
1. Increased investment in AI infrastructure is recommended
2. Focus on developer productivity tools shows high market potential
3. Regulatory compliance should be prioritized for AI applications

## Strategic Insights
The convergence of multiple data sources indicates a robust growth trajectory for AI technologies with significant market opportunities.
"""

    return StepOutput(
        step_name="final_reasoning_step",  # Use function name
        content=reasoning.strip(),
        success=True,
    )


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not available")
class TestAccessMultiplePreviousStepsIntegration:
    """Integration tests for accessing multiple previous step outputs with real agents."""

    def test_multi_step_access_workflow_non_streaming(
        self, workflow_storage, hackernews_agent, web_agent, reasoning_agent
    ):
        """Test workflow with access to multiple previous steps without streaming."""
        # Create research steps
        research_hackernews = Step(
            name="research_hackernews",
            agent=hackernews_agent,
            description="Research latest tech trends from Hacker News",
        )

        research_web = Step(
            name="research_web",
            agent=web_agent,
            description="Comprehensive web research on the topic",
        )

        # Custom function step with access to previous outputs
        comprehensive_report_step = Step(
            name="comprehensive_report",
            executor=create_comprehensive_report,
            description="Create comprehensive report from all research sources",
        )

        # Final reasoning step
        reasoning_step = Step(
            name="final_reasoning",
            agent=reasoning_agent,
            description="Apply reasoning to create final insights and recommendations",
        )

        workflow = Workflow(
            name="Enhanced Research Workflow",
            storage=workflow_storage,
            steps=[
                research_hackernews,
                research_web,
                comprehensive_report_step,  # Has access to both previous steps
                reasoning_step,  # Gets the comprehensive report
            ],
        )

        response = workflow.run(message="Latest developments in artificial intelligence")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.content) > 200

        # Verify we have outputs from all steps
        assert len(response.step_responses) == 4

        # Verify the comprehensive report contains data from multiple sources
        comprehensive_step = response.step_responses[2]
        assert isinstance(comprehensive_step, StepOutput)
        assert comprehensive_step.step_name == "comprehensive_report"
        assert "HackerNews Insights" in comprehensive_step.content
        assert "Web Research Findings" in comprehensive_step.content
        assert "Step Access Verification" in comprehensive_step.content

    def test_multi_step_access_workflow_streaming(self, workflow_storage, hackernews_agent, web_agent, reasoning_agent):
        """Test workflow with access to multiple previous steps with streaming."""
        # Create the same workflow structure
        research_hackernews = Step(
            name="research_hackernews",
            agent=hackernews_agent,
            description="Research latest tech trends from Hacker News",
        )

        research_web = Step(
            name="research_web",
            agent=web_agent,
            description="Comprehensive web research on the topic",
        )

        comprehensive_report_step = Step(
            name="comprehensive_report",
            executor=create_comprehensive_report,
            description="Create comprehensive report from all research sources",
        )

        reasoning_step = Step(
            name="final_reasoning",
            agent=reasoning_agent,
            description="Apply reasoning to create final insights and recommendations",
        )

        workflow = Workflow(
            name="Enhanced Research Workflow Streaming",
            storage=workflow_storage,
            steps=[
                research_hackernews,
                research_web,
                comprehensive_report_step,
                reasoning_step,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="AI and machine learning trends", stream=True):
            events.append(event)

        # Verify streaming events were generated
        assert len(events) > 0

        # Check for final completion event
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "AI" in completed_events[0].content or "artificial intelligence" in completed_events[0].content.lower()

    @pytest.mark.asyncio
    async def test_async_multi_step_access_workflow(self, workflow_storage, hackernews_agent, web_agent):
        """Test async workflow with access to multiple previous steps."""
        research_hackernews = Step(
            name="research_hackernews",
            agent=hackernews_agent,
            description="Research latest tech trends from Hacker News",
        )

        research_web = Step(
            name="research_web",
            agent=web_agent,
            description="Comprehensive web research on the topic",
        )

        comprehensive_report_step = Step(
            name="comprehensive_report",
            executor=create_comprehensive_report,
            description="Create comprehensive report from all research sources",
        )

        workflow = Workflow(
            name="Async Enhanced Research Workflow",
            storage=workflow_storage,
            steps=[
                research_hackernews,
                research_web,
                comprehensive_report_step,
            ],
        )

        response = await workflow.arun(message="Future of AI technology")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.content) > 100

        # Verify the comprehensive report was created with access to previous steps
        comprehensive_step = response.step_responses[2]
        assert comprehensive_step.step_name == "comprehensive_report"
        assert "Comprehensive Research Report" in comprehensive_step.content

    @pytest.mark.asyncio
    async def test_async_multi_step_access_workflow_streaming(self, workflow_storage, hackernews_agent, web_agent):
        """Test async workflow with access to multiple previous steps and streaming."""
        research_hackernews = Step(
            name="research_hackernews",
            agent=hackernews_agent,
            description="Research latest tech trends from Hacker News",
        )

        research_web = Step(
            name="research_web",
            agent=web_agent,
            description="Comprehensive web research on the topic",
        )

        comprehensive_report_step = Step(
            name="comprehensive_report",
            executor=create_comprehensive_report,
            description="Create comprehensive report from all research sources",
        )

        workflow = Workflow(
            name="Async Enhanced Research Streaming Workflow",
            storage=workflow_storage,
            steps=[
                research_hackernews,
                research_web,
                comprehensive_report_step,
            ],
        )

        # Collect async streaming events
        events = []
        async for event in await workflow.arun(message="Emerging AI technologies", stream=True):
            events.append(event)

        # Verify streaming and multi-step access
        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Comprehensive Research Report" in completed_events[0].content


class TestAccessMultiplePreviousStepsWithFunctions:
    """Integration tests for accessing multiple previous step outputs using function executors (no API keys required)."""

    def test_function_multi_step_access_non_streaming(self, workflow_storage):
        """Test function-based workflow with access to multiple previous steps."""
        workflow = Workflow(
            name="Function-based Multi-Step Access Workflow",
            storage=workflow_storage,
            steps=[
                hackernews_research_step,
                web_research_step,
                data_analysis_step,
                create_comprehensive_report,  # Has access to all previous steps
                final_reasoning_step,  # Gets the comprehensive report
            ],
        )

        response = workflow.run(message="AI market analysis")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert len(response.content) > 200

        # Verify we have outputs from all steps
        assert len(response.step_responses) == 5

        # Verify the comprehensive report step accessed multiple previous steps
        comprehensive_step = response.step_responses[3]
        assert isinstance(comprehensive_step, StepOutput)
        assert comprehensive_step.step_name == "create_comprehensive_report"  # Function name
        assert "Comprehensive Research Report" in comprehensive_step.content
        assert "HackerNews Insights" in comprehensive_step.content
        assert "Web Research Findings" in comprehensive_step.content
        assert "Data Analysis" in comprehensive_step.content
        assert "Step Access Verification" in comprehensive_step.content

        # Verify step access worked
        assert "HackerNews step found: Yes" in comprehensive_step.content
        assert "Web step found: Yes" in comprehensive_step.content

    def test_function_multi_step_access_streaming(self, workflow_storage):
        """Test function-based workflow with access to multiple previous steps and streaming."""
        workflow = Workflow(
            name="Function-based Multi-Step Access Streaming Workflow",
            storage=workflow_storage,
            steps=[
                hackernews_research_step,
                web_research_step,
                create_comprehensive_report,
                final_reasoning_step,
            ],
        )

        # Collect streaming events
        events = []
        for event in workflow.run(message="Technology trend analysis", stream=True):
            events.append(event)

        # Verify streaming events were generated
        assert len(events) > 0

        # Check for final completion event
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Final Analysis and Recommendations" in completed_events[0].content

    @pytest.mark.asyncio
    async def test_async_function_multi_step_access_non_streaming(self, workflow_storage):
        """Test async function-based workflow with access to multiple previous steps."""
        workflow = Workflow(
            name="Async Function Multi-Step Access Workflow",
            storage=workflow_storage,
            steps=[
                hackernews_research_step,
                web_research_step,
                create_comprehensive_report,
            ],
        )

        response = await workflow.arun(message="AI development trends")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None
        assert "Comprehensive Research Report" in response.content

        # Verify the comprehensive report accessed previous steps
        comprehensive_step = response.step_responses[2]
        assert comprehensive_step.step_name == "create_comprehensive_report"  # Function name
        assert "hackernews_research_step" in str(comprehensive_step.content)
        assert "web_research_step" in str(comprehensive_step.content)

    @pytest.mark.asyncio
    async def test_async_function_multi_step_access_streaming(self, workflow_storage):
        """Test async function-based workflow with access to multiple previous steps and streaming."""
        workflow = Workflow(
            name="Async Function Multi-Step Access Streaming Workflow",
            storage=workflow_storage,
            steps=[
                hackernews_research_step,
                web_research_step,
                create_comprehensive_report,
                final_reasoning_step,
            ],
        )

        # Collect async streaming events
        events = []
        async for event in await workflow.arun(message="Future technology predictions", stream=True):
            events.append(event)

        # Verify streaming and multi-step access
        assert len(events) > 0
        completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
        assert len(completed_events) == 1
        assert "Strategic Insights" in completed_events[0].content

    def test_step_content_access_methods(self, workflow_storage):
        """Test different methods of accessing previous step content."""

        def test_access_methods(step_input: StepInput) -> StepOutput:
            """Test function that verifies all access methods work correctly."""
            # Test different access methods (using function names)
            hackernews_content = step_input.get_step_content("hackernews_research_step")
            web_content = step_input.get_step_content("web_research_step")
            all_content = step_input.get_all_previous_content()

            # Test getting specific step outputs
            hackernews_output = step_input.get_step_output("hackernews_research_step")
            web_output = step_input.get_step_output("web_research_step")

            # Test accessing previous_steps_outputs directly
            available_steps = (
                list(step_input.previous_steps_outputs.keys()) if step_input.previous_steps_outputs else []
            )

            # Verify workflow message access
            workflow_msg = step_input.workflow_message or step_input.message or ""

            verification_report = f"""# Step Access Methods Verification

## get_step_content() Results:
- HackerNews content length: {len(hackernews_content) if hackernews_content else 0}
- Web content length: {len(web_content) if web_content else 0}

## get_all_previous_content() Result:
- Total content length: {len(all_content)}

## get_step_output() Results:
- HackerNews output available: {"Yes" if hackernews_output else "No"}
- Web output available: {"Yes" if web_output else "No"}

## Available Steps:
{", ".join(available_steps) if available_steps else "None"}

## Workflow Message:
{workflow_msg}

## Previous Step Content:
{step_input.previous_step_content[:100] if step_input.previous_step_content else "None"}...
"""

            return StepOutput(
                step_name="test_access_methods",  # Use function name
                content=verification_report.strip(),
                success=True,
            )

        workflow = Workflow(
            name="Step Access Methods Test Workflow",
            storage=workflow_storage,
            steps=[
                hackernews_research_step,
                web_research_step,
                test_access_methods,
            ],
        )

        response = workflow.run(message="Testing step access methods")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None

        # Verify the access methods test worked
        test_step = response.step_responses[2]
        assert test_step.step_name == "test_access_methods"  # Function name
        assert "Step Access Methods Verification" in test_step.content
        assert "HackerNews content length:" in test_step.content
        assert "Web content length:" in test_step.content
        assert "HackerNews output available: Yes" in test_step.content
        assert "Web output available: Yes" in test_step.content
        assert "hackernews_research_step, web_research_step" in test_step.content

    def test_empty_previous_steps_handling(self, workflow_storage):
        """Test workflow behavior when there are no previous steps."""

        def first_step_test(step_input: StepInput) -> StepOutput:
            """Test function that checks behavior with no previous steps."""
            # These should return empty/None values for the first step
            all_content = step_input.get_all_previous_content()
            step_content = step_input.get_step_content("nonexistent_step")
            step_output = step_input.get_step_output("nonexistent_step")
            previous_content = step_input.previous_step_content

            report = f"""# First Step Test Results

## Access Methods with No Previous Steps:
- get_all_previous_content(): '{all_content}'
- get_step_content('nonexistent'): '{step_content}'
- get_step_output('nonexistent'): {step_output}
- previous_step_content: '{previous_content}'
- workflow_message: '{step_input.workflow_message or step_input.message}'
"""

            return StepOutput(step_name="first_step_test", content=report.strip(), success=True)

        workflow = Workflow(
            name="Empty Previous Steps Test Workflow",
            storage=workflow_storage,
            steps=[first_step_test],
        )

        response = workflow.run(message="Testing empty previous steps")

        assert isinstance(response, WorkflowRunResponse)
        assert response.content is not None

        # Verify the first step handled empty previous steps gracefully
        test_step = response.step_responses[0]
        assert test_step.step_name == "first_step_test"
        assert "First Step Test Results" in test_step.content
        assert "Testing empty previous steps" in test_step.content
