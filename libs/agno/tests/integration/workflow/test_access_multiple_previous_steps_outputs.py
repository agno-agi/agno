"""Integration tests for accessing multiple previous step outputs in workflows."""

import pytest

from agno.run.v2.workflow import WorkflowCompletedEvent, WorkflowRunResponse
from agno.workflow.v2 import Workflow
from agno.workflow.v2.types import StepInput, StepOutput


# Helper functions
def research_step(step_input: StepInput) -> StepOutput:
    """Research step."""
    return StepOutput(step_name="research_step", content=f"Research: {step_input.message}", success=True)


def analysis_step(step_input: StepInput) -> StepOutput:
    """Analysis step."""
    return StepOutput(step_name="analysis_step", content="Analysis of research data", success=True)


def report_step(step_input: StepInput) -> StepOutput:
    """Report step that accesses multiple previous outputs."""
    # Get specific step outputs
    research_data = step_input.get_step_content("research_step") or ""
    analysis_data = step_input.get_step_content("analysis_step") or ""

    # Get all previous content
    all_content = step_input.get_all_previous_content()

    report = f"""Report:
Research: {research_data}
Analysis: {analysis_data}
Total Content Length: {len(all_content)}
Available Steps: {list(step_input.previous_step_outputs.keys())}"""

    return StepOutput(step_name="report_step", content=report, success=True)


def test_basic_access(workflow_storage):
    """Test basic access to previous steps."""
    workflow = Workflow(
        name="Basic Access", storage=workflow_storage, steps=[research_step, analysis_step, report_step]
    )

    response = workflow.run(message="test topic")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 3

    # Verify report contains data from previous steps
    report = response.step_responses[2]
    assert "Research:" in report.content
    assert "Analysis:" in report.content
    assert "research_step" in report.content
    assert "analysis_step" in report.content


def test_streaming_access(workflow_storage):
    """Test streaming with multiple step access."""
    workflow = Workflow(
        name="Streaming Access", storage=workflow_storage, steps=[research_step, analysis_step, report_step]
    )

    events = list(workflow.run(message="test topic", stream=True))

    # Verify events
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Report:" in completed_events[0].content


@pytest.mark.asyncio
async def test_async_access(workflow_storage):
    """Test async execution with multiple step access."""
    workflow = Workflow(
        name="Async Access", storage=workflow_storage, steps=[research_step, analysis_step, report_step]
    )

    response = await workflow.arun(message="test topic")
    assert isinstance(response, WorkflowRunResponse)
    assert len(response.step_responses) == 3
    assert "Report:" in response.content


@pytest.mark.asyncio
async def test_async_streaming_access(workflow_storage):
    """Test async streaming with multiple step access."""
    workflow = Workflow(
        name="Async Streaming", storage=workflow_storage, steps=[research_step, analysis_step, report_step]
    )

    events = []
    async for event in await workflow.arun(message="test topic", stream=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Report:" in completed_events[0].content
