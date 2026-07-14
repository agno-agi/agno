"""Integration tests for structured output flow between workflow steps."""

from typing import List

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput


# Define structured models for testing
class ResearchData(BaseModel):
    """Structured research data."""

    topic: str = Field(description="The research topic")
    insights: List[str] = Field(description="Key insights", min_items=2)
    confidence: float = Field(description="Confidence score", ge=0.0, le=1.0)


class AnalysisResult(BaseModel):
    """Structured analysis result."""

    summary: str = Field(description="Analysis summary")
    recommendations: List[str] = Field(description="Recommendations", min_items=2)
    priority: str = Field(description="Priority level")


class FinalReport(BaseModel):
    """Final structured report."""

    title: str = Field(description="Report title")
    content: str = Field(description="Report content")
    metrics: List[str] = Field(description="Success metrics", min_items=1)


# Test functions for structured output
def research_function(step_input: StepInput) -> StepOutput:
    """Function that returns structured data."""
    research_data = ResearchData(
        topic="AI Testing", insights=["AI is evolving rapidly", "Testing is crucial for AI systems"], confidence=0.85
    )
    return StepOutput(content=research_data)


def analysis_function(step_input: StepInput) -> StepOutput:
    """Function that processes structured input and returns structured output."""
    # Access the structured data from previous step
    previous_data = step_input.previous_step_content

    # Verify we received structured data
    assert isinstance(previous_data, ResearchData)
    assert previous_data.topic == "AI Testing"
    assert len(previous_data.insights) == 2

    # Create structured output based on input
    analysis_result = AnalysisResult(
        summary=f"Analysis of {previous_data.topic}",
        recommendations=["Implement testing framework", "Monitor AI performance"],
        priority="High",
    )
    return StepOutput(content=analysis_result)


def final_function(step_input: StepInput) -> StepOutput:
    """Function that creates final report from structured data."""
    # Access structured data from previous step
    analysis_data = step_input.previous_step_content

    # Verify we received structured data
    assert isinstance(analysis_data, AnalysisResult)
    assert analysis_data.priority == "High"

    # Create final structured output
    final_report = FinalReport(
        title="AI Testing Report",
        content=f"Report based on: {analysis_data.summary}",
        metrics=["Test coverage", "Performance metrics"],
    )
    return StepOutput(content=final_report)


def test_structured_output_function_flow_sync(shared_db):
    """Test structured output flow between functions - sync."""
    workflow = Workflow(
        name="Structured Function Flow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_function),
            Step(name="analysis", executor=analysis_function),
            Step(name="final", executor=final_function),
        ],
    )

    response = workflow.run(input="test structured flow")

    # Verify we have all step responses
    assert len(response.step_results) == 3

    # Verify each step received and produced structured data
    research_output = response.step_results[0]
    analysis_output = response.step_results[1]
    final_output = response.step_results[2]

    # Check types
    assert isinstance(research_output.content, ResearchData)
    assert isinstance(analysis_output.content, AnalysisResult)
    assert isinstance(final_output.content, FinalReport)

    # Check data flow
    assert research_output.content.topic == "AI Testing"
    assert analysis_output.content.summary == "Analysis of AI Testing"
    assert final_output.content.title == "AI Testing Report"


def test_structured_output_function_flow_streaming(shared_db):
    """Test structured output flow between functions - streaming."""
    workflow = Workflow(
        name="Structured Function Flow Streaming",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_function),
            Step(name="analysis", executor=analysis_function),
            Step(name="final", executor=final_function),
        ],
    )

    events = list(workflow.run(input="test structured flow", stream=True))

    # Find the workflow completed event
    from agno.run.workflow import WorkflowCompletedEvent

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Verify structured data in final output
    final_content = completed_events[0].content
    assert isinstance(final_content, FinalReport)
    assert final_content.title == "AI Testing Report"


@pytest.mark.asyncio
async def test_structured_output_function_flow_async(shared_db):
    """Test structured output flow between functions - async."""
    workflow = Workflow(
        name="Async Structured Function Flow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_function),
            Step(name="analysis", executor=analysis_function),
            Step(name="final", executor=final_function),
        ],
    )

    response = await workflow.arun(input="test structured flow")

    # Verify we have all step responses
    assert len(response.step_results) == 3

    # Verify final output is structured
    final_output = response.step_results[2]
    assert isinstance(final_output.content, FinalReport)
    assert final_output.content.title == "AI Testing Report"


@pytest.mark.asyncio
async def test_structured_output_function_flow_async_streaming(shared_db):
    """Test structured output flow between functions - async streaming."""
    workflow = Workflow(
        name="Async Structured Function Flow Streaming",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_function),
            Step(name="analysis", executor=analysis_function),
            Step(name="final", executor=final_function),
        ],
    )

    events = []
    async for event in workflow.arun(input="test structured flow", stream=True):
        events.append(event)

    # Find the workflow completed event
    from agno.run.workflow import WorkflowCompletedEvent

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Verify structured data in final output
    final_content = completed_events[0].content
    assert isinstance(final_content, FinalReport)
    assert final_content.title == "AI Testing Report"


def test_structured_output_agent_flow_sync(shared_db):
    """Test structured output flow between agents - sync."""
    # Create agents with structured response models
    research_agent = Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide research data in structured format"],
    )

    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=AnalysisResult,
        instructions=["Analyze the research data and provide structured results"],
    )

    final_agent = Agent(
        name="Final Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=FinalReport,
        instructions=["Create a final report based on the analysis"],
    )

    workflow = Workflow(
        name="Structured Agent Flow",
        db=shared_db,
        steps=[
            Step(name="research", agent=research_agent),
            Step(name="analysis", agent=analysis_agent),
            Step(name="final", agent=final_agent),
        ],
    )

    response = workflow.run(input="Research AI testing methodologies")

    # Verify we have all step responses
    assert len(response.step_results) == 3

    # Verify each step produced structured data
    research_output = response.step_results[0]
    analysis_output = response.step_results[1]
    final_output = response.step_results[2]

    # Check that outputs are structured (BaseModel instances)
    assert isinstance(research_output.content, ResearchData)
    assert isinstance(analysis_output.content, AnalysisResult)
    assert isinstance(final_output.content, FinalReport)


def test_structured_output_agent_flow_streaming(shared_db):
    """Test structured output flow between agents - streaming."""
    # Create agents with structured response models
    research_agent = Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide research data in structured format"],
    )

    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=AnalysisResult,
        instructions=["Analyze the research data and provide structured results"],
    )

    workflow = Workflow(
        name="Structured Agent Flow Streaming",
        db=shared_db,
        steps=[
            Step(name="research", agent=research_agent),
            Step(name="analysis", agent=analysis_agent),
        ],
    )

    events = list(workflow.run(input="Research AI testing methodologies", stream=True))

    # Find the workflow completed event
    from agno.run.workflow import WorkflowCompletedEvent

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Verify structured data in final output
    final_content = completed_events[0].content
    assert isinstance(final_content, AnalysisResult)


@pytest.mark.asyncio
async def test_structured_output_agent_flow_async(shared_db):
    """Test structured output flow between agents - async."""
    # Create agents with structured response models
    research_agent = Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide research data in structured format"],
    )

    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=AnalysisResult,
        instructions=["Analyze the research data and provide structured results"],
    )

    workflow = Workflow(
        name="Async Structured Agent Flow",
        db=shared_db,
        steps=[
            Step(name="research", agent=research_agent),
            Step(name="analysis", agent=analysis_agent),
        ],
    )

    response = await workflow.arun(input="Research AI testing methodologies")

    # Verify we have all step responses
    assert len(response.step_results) == 2

    # Verify structured outputs
    research_output = response.step_results[0]
    analysis_output = response.step_results[1]

    assert isinstance(research_output.content, ResearchData)
    assert isinstance(analysis_output.content, AnalysisResult)


@pytest.mark.asyncio
async def test_structured_output_agent_flow_async_streaming(shared_db):
    """Test structured output flow between agents - async streaming."""
    # Create agents with structured response models
    research_agent = Agent(
        name="Research Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide research data in structured format"],
    )

    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=AnalysisResult,
        instructions=["Analyze the research data and provide structured results"],
    )

    workflow = Workflow(
        name="Async Structured Agent Flow Streaming",
        db=shared_db,
        steps=[
            Step(name="research", agent=research_agent),
            Step(name="analysis", agent=analysis_agent),
        ],
    )

    events = [event async for event in workflow.arun(input="Research AI testing methodologies", stream=True)]

    # Find the workflow completed event
    from agno.run.workflow import WorkflowCompletedEvent

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Verify structured data in final output
    final_content = completed_events[0].content
    assert isinstance(final_content, AnalysisResult)


def test_structured_output_team_flow_sync(shared_db):
    """Test structured output flow with team - sync (simplified)."""
    # Create minimal team with structured response model
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Provide brief research data"],
    )

    research_team = Team(
        name="Research Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide structured research data"],
    )

    workflow = Workflow(
        name="Simple Team Flow",
        db=shared_db,
        steps=[
            Step(name="research", team=research_team),
        ],
    )

    response = workflow.run(input="Brief AI research")

    # Verify structured output
    assert len(response.step_results) == 1
    research_output = response.step_results[0]
    assert isinstance(research_output.content, ResearchData)


def test_structured_output_team_flow_streaming(shared_db):
    """Test structured output flow with team - streaming (simplified)."""
    # Create minimal team
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Provide brief research data"],
    )

    research_team = Team(
        name="Research Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide structured research data"],
    )

    workflow = Workflow(
        name="Simple Team Flow Streaming",
        db=shared_db,
        steps=[
            Step(name="research", team=research_team),
        ],
    )

    events = list(workflow.run(input="Brief AI research", stream=True))

    # Find the workflow completed event
    from agno.run.workflow import WorkflowCompletedEvent

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Verify structured data in final output
    final_content = completed_events[0].content
    assert isinstance(final_content, ResearchData)


@pytest.mark.asyncio
async def test_structured_output_team_flow_async(shared_db):
    """Test structured output flow with team - async (simplified)."""
    # Create minimal team
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Provide brief research data"],
    )

    research_team = Team(
        name="Research Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide structured research data"],
    )

    workflow = Workflow(
        name="Simple Async Team Flow",
        db=shared_db,
        steps=[
            Step(name="research", team=research_team),
        ],
    )

    response = await workflow.arun(input="Brief AI research")

    # Verify structured output
    assert len(response.step_results) == 1
    research_output = response.step_results[0]
    assert isinstance(research_output.content, ResearchData)


@pytest.mark.asyncio
async def test_structured_output_team_flow_async_streaming(shared_db):
    """Test structured output flow with team - async streaming (simplified)."""
    # Create minimal team
    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Provide brief research data"],
    )

    research_team = Team(
        name="Research Team",
        members=[researcher],
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=ResearchData,
        instructions=["Provide structured research data"],
    )

    workflow = Workflow(
        name="Simple Async Team Flow Streaming",
        db=shared_db,
        steps=[
            Step(name="research", team=research_team),
        ],
    )

    events = [event async for event in workflow.arun(input="Brief AI research", stream=True)]

    # Find the workflow completed event
    from agno.run.workflow import WorkflowCompletedEvent

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1

    # Verify structured data in final output
    final_content = completed_events[0].content
    assert isinstance(final_content, ResearchData)


def test_mixed_structured_output_flow(shared_db):
    """Test mixed structured output flow (function -> agent -> team) - simplified."""
    # Create minimal agent
    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=AnalysisResult,
        instructions=["Analyze briefly"],
    )

    # Create minimal team
    final_member = Agent(
        name="Report Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Create brief reports"],
    )

    final_team = Team(
        name="Final Team",
        members=[final_member],
        model=OpenAIChat(id="gpt-4o-mini"),
        output_schema=FinalReport,
        instructions=["Create brief structured report"],
    )

    workflow = Workflow(
        name="Mixed Structured Flow",
        db=shared_db,
        steps=[
            Step(name="research", executor=research_function),  # Function (fast)
            Step(name="analysis", agent=analysis_agent),  # Agent
            Step(name="final", team=final_team),  # Team
        ],
    )

    response = workflow.run(input="test mixed flow")

    # Verify we have all step responses
    assert len(response.step_results) == 3

    # Verify each step produced structured data
    research_output = response.step_results[0]
    analysis_output = response.step_results[1]
    final_output = response.step_results[2]

    # Check that outputs are structured
    assert isinstance(research_output.content, ResearchData)
    assert isinstance(analysis_output.content, AnalysisResult)
    assert isinstance(final_output.content, FinalReport)


def test_structured_output_with_workflow_components(shared_db):
    """Test structured output flow with workflow components (Steps, Loop, Condition)."""
    from agno.workflow import Condition, Loop, Steps

    # Simple condition function
    def should_continue(step_input: StepInput) -> bool:
        """Simple condition - always true for testing."""
        return True

    # Simple loop condition
    def loop_end_condition(outputs):
        """End loop after 1 iteration."""
        return len(outputs) >= 1

    # Create a workflow with structured data flowing through different components
    workflow = Workflow(
        name="Simple Component Flow",
        db=shared_db,
        steps=[
            Steps(
                name="research_steps",
                steps=[
                    Step(name="research", executor=research_function),
                ],
            ),
            Condition(
                name="analysis_condition",
                evaluator=should_continue,
                steps=[Step(name="analysis", executor=analysis_function)],
            ),
            Loop(
                name="final_loop",
                steps=[Step(name="final", executor=final_function)],
                end_condition=loop_end_condition,
                max_iterations=1,
            ),
        ],
    )

    response = workflow.run(input="test simple component flow")

    # Verify we have all step responses
    assert len(response.step_results) == 3

    # Handle the actual structure - some might be lists
    steps_output = response.step_results[0]
    condition_output = response.step_results[1]
    loop_output = response.step_results[2]

    assert hasattr(steps_output, "steps") and steps_output.steps
    actual_research_step = steps_output.steps[0]  # Get the actual research step
    assert isinstance(actual_research_step.content, ResearchData)

    # Condition should have processed the structured data - access the nested step content
    assert hasattr(condition_output, "steps") and condition_output.steps
    actual_analysis_step = condition_output.steps[0]  # Get the actual analysis step
    assert isinstance(actual_analysis_step.content, AnalysisResult)

    # Loop should have structured output - access the nested step content
    assert hasattr(loop_output, "steps") and loop_output.steps
    actual_final_step = loop_output.steps[0]  # Get the actual final step
    assert isinstance(actual_final_step.content, FinalReport)
    assert actual_final_step.content.title == "AI Testing Report"
