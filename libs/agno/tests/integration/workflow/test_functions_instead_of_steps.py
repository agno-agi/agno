"""Test custom execution functions in workflows."""

from typing import Iterator, Union

import pytest

from agno.agent.agent import Agent
from agno.run.base import RunStatus
from agno.run.response import RunResponseEvent
from agno.run.v2.workflow import WorkflowCompletedEvent
from agno.workflow.v2.types import WorkflowExecutionInput
from agno.workflow.v2.workflow import Workflow, WorkflowRunResponse


# Mock agents for testing
@pytest.fixture
def simple_agent():
    """Create a simple agent for testing."""
    return Agent(
        name="TestAgent",
        instructions="You are a test agent that provides mock responses.",
    )


@pytest.fixture
def research_agent():
    """Create a research agent for testing."""
    return Agent(
        name="ResearchAgent",
        instructions="You are a research agent that gathers information.",
    )


@pytest.fixture
def content_agent():
    """Create a content planning agent for testing."""
    return Agent(
        name="ContentAgent",
        instructions="You are a content planning agent that creates content strategies.",
    )


def test_simple_custom_execution_non_streaming(workflow_storage):
    """Test simple custom execution function (non-streaming)."""

    def simple_custom_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Simple custom execution that returns a string."""
        message = execution_input.message or "No message"
        return f"Custom execution processed: {message}"

    workflow = Workflow(
        name="Simple Custom Execution Workflow",
        storage=workflow_storage,
        steps=simple_custom_execution,
    )

    response = workflow.run(message="Test message")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "Custom execution processed: Test message" in response.content


def test_agent_based_custom_execution_non_streaming(workflow_storage):
    """Test custom execution function using an agent (non-streaming)."""

    def agent_custom_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that uses an agent."""
        message = execution_input.message or "Default topic"

        # Mock agent response instead of making actual API call
        mock_response = f"Agent analysis of: {message}"
        return mock_response

    workflow = Workflow(
        name="Agent Custom Execution Workflow",
        storage=workflow_storage,
        steps=agent_custom_execution,
    )

    response = workflow.run(message="AI trends")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "Agent analysis of: AI trends" in response.content


def test_multi_step_custom_execution_non_streaming(workflow_storage):
    """Test custom execution function that simulates multiple steps."""

    def multi_step_custom_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that simulates multiple processing steps."""
        message = execution_input.message or "Default topic"

        # Simulate research step
        research_results = f"Research on {message}: Found key insights about trends and developments."

        # Simulate analysis step
        analysis_results = f"Analysis based on research: {research_results[:50]}... Key findings include market growth."

        # Simulate final content creation
        final_content = (
            f"Final Report:\n\nTopic: {message}\n\nResearch: {research_results}\n\nAnalysis: {analysis_results}"
        )

        return final_content

    workflow = Workflow(
        name="Multi-Step Custom Execution Workflow",
        storage=workflow_storage,
        steps=multi_step_custom_execution,
    )

    response = workflow.run(message="Technology market analysis")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "Final Report:" in response.content
    assert "Technology market analysis" in response.content
    assert "Research on Technology market analysis" in response.content


def test_custom_execution_streaming(workflow_storage):
    """Test custom execution function with streaming."""

    def streaming_custom_execution(
        workflow: Workflow, execution_input: WorkflowExecutionInput
    ) -> Iterator[Union[str, RunResponseEvent]]:
        """Custom execution that yields streaming content."""
        message = execution_input.message or "Default topic"

        # Yield intermediate steps
        yield f"Starting analysis of: {message}"
        yield "Gathering research data..."
        yield "Processing insights..."

        # Yield final result
        yield f"Complete analysis for {message}: Comprehensive insights and recommendations."

    workflow = Workflow(
        name="Streaming Custom Execution Workflow",
        storage=workflow_storage,
        steps=streaming_custom_execution,
    )

    # Collect streaming events
    events = []
    for event in workflow.run(message="AI market trends", stream=True):
        events.append(event)

    # Verify streaming events were generated
    assert len(events) > 0

    # Check for final completion event
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Complete analysis for AI market trends" in completed_events[0].content


def test_custom_execution_with_error_handling(workflow_storage):
    """Test custom execution function error handling."""

    def failing_custom_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that raises an error."""
        try:
            raise ValueError("Custom execution failed!")
        except ValueError as e:
            return f"Error occurred: {str(e)}"

    workflow = Workflow(
        name="Failing Custom Execution Workflow",
        storage=workflow_storage,
        steps=failing_custom_execution,
    )

    response = workflow.run(message="Test message")

    assert isinstance(response, WorkflowRunResponse)
    assert response.status == RunStatus.completed  # Now completed since we handle the error
    assert "Custom execution failed!" in response.content


def test_custom_execution_with_workflow_access(workflow_storage):
    """Test custom execution function accessing workflow properties."""

    def workflow_aware_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that uses workflow properties."""
        workflow_name = workflow.name or "Unknown Workflow"
        message = execution_input.message or "No message"

        return f"Workflow '{workflow_name}' processed message: {message}"

    workflow = Workflow(
        name="Workflow-Aware Custom Execution",
        storage=workflow_storage,
        steps=workflow_aware_execution,
    )

    response = workflow.run(message="Test workflow access")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "Workflow 'Workflow-Aware Custom Execution' processed message: Test workflow access" in response.content


def test_custom_execution_with_execution_input_properties(workflow_storage):
    """Test custom execution function accessing execution input properties."""

    def input_aware_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that examines all execution input properties."""
        components = []

        if execution_input.message:
            components.append(f"Message: {execution_input.message}")

        if execution_input.images:
            components.append(f"Images: {len(execution_input.images)} provided")

        if execution_input.videos:
            components.append(f"Videos: {len(execution_input.videos)} provided")

        if execution_input.audio:
            components.append(f"Audio: {len(execution_input.audio)} provided")

        return "Execution Input Analysis:\n" + "\n".join(components)

    workflow = Workflow(
        name="Input-Aware Custom Execution",
        storage=workflow_storage,
        steps=input_aware_execution,
    )

    # Pass data via message_data instead of user_id/session_id
    message = {"user_id": "test_user", "session_id": "test_session"}
    response = workflow.run(message=message)

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "test_user" in str(response.content)


async def test_async_custom_execution_non_streaming(workflow_storage):
    """Test async custom execution function (non-streaming)."""

    async def async_custom_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Async custom execution function."""
        import asyncio

        message = execution_input.message or "No message"

        # Simulate async work
        await asyncio.sleep(0.01)

        return f"Async custom execution processed: {message}"

    workflow = Workflow(
        name="Async Custom Execution Workflow",
        storage=workflow_storage,
        steps=async_custom_execution,
    )

    response = await workflow.arun(message="Async test message")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "Async custom execution processed: Async test message" in response.content


async def test_async_custom_execution_streaming(workflow_storage):
    """Test async custom execution function with streaming."""

    async def async_streaming_custom_execution(workflow: Workflow, execution_input: WorkflowExecutionInput):
        """Async custom execution that yields streaming content."""
        import asyncio

        message = execution_input.message or "Default topic"

        # Yield intermediate steps
        yield f"Async: Starting analysis of: {message}"
        await asyncio.sleep(0.01)
        yield "Async: Gathering research data..."
        await asyncio.sleep(0.01)
        yield "Async: Processing insights..."
        await asyncio.sleep(0.01)

        # Yield final result
        yield f"Async: Complete analysis for {message}: Comprehensive insights and recommendations."

    workflow = Workflow(
        name="Async Streaming Custom Execution Workflow",
        storage=workflow_storage,
        steps=async_streaming_custom_execution,
    )

    # Collect async streaming events
    events = []
    async for event in await workflow.arun(message="Async AI trends", stream=True):
        events.append(event)

    # Verify streaming events were generated
    assert len(events) > 0

    # Check for final completion event
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Async: Complete analysis for Async AI trends" in completed_events[0].content


def test_custom_execution_return_types(workflow_storage):
    """Test custom execution function with different return types."""

    def dict_return_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that returns a dictionary."""
        result = {
            "status": "success",
            "message": execution_input.message,
            "analysis": "Complete analysis performed",
        }
        return str(result)  # Convert dict to string explicitly

    workflow = Workflow(
        name="Dict Return Custom Execution",
        storage=workflow_storage,
        steps=dict_return_execution,
    )

    response = workflow.run(message="Dict test")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    # Check for string representation of dict values
    assert "'status': 'success'" in response.content
    assert "'message': 'Dict test'" in response.content


def test_custom_execution_complex_workflow_simulation(workflow_storage):
    """Test custom execution that simulates a complex multi-agent workflow."""

    def complex_workflow_simulation(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution simulating research -> analysis -> content creation."""
        topic = execution_input.message or "General topic"

        # Simulate research phase
        research_phase = f"Research Phase Results for '{topic}':\n"
        research_phase += "- Found 15 relevant articles\n"
        research_phase += "- Identified 5 key trends\n"
        research_phase += "- Gathered expert opinions\n\n"

        # Simulate analysis phase
        analysis_phase = "Analysis Phase Results:\n"
        analysis_phase += f"- Processed research on {topic}\n"
        analysis_phase += "- Generated insights and patterns\n"
        analysis_phase += "- Ranked findings by importance\n\n"

        # Simulate content creation phase
        content_phase = "Content Creation Phase:\n"
        content_phase += f"- Created comprehensive report on {topic}\n"
        content_phase += "- Structured findings into actionable insights\n"
        content_phase += "- Prepared executive summary\n\n"

        # Final output
        final_output = "COMPREHENSIVE ANALYSIS REPORT\n\n"
        final_output += f"Topic: {topic}\n\n"
        final_output += research_phase + analysis_phase + content_phase
        final_output += "CONCLUSION: Analysis complete with actionable recommendations."

        return final_output

    workflow = Workflow(
        name="Complex Workflow Simulation",
        storage=workflow_storage,
        steps=complex_workflow_simulation,
    )

    response = workflow.run(message="Artificial Intelligence Market Trends")

    assert isinstance(response, WorkflowRunResponse)
    assert response.content is not None
    assert response.status == RunStatus.completed
    assert "COMPREHENSIVE ANALYSIS REPORT" in response.content
    assert "Research Phase Results" in response.content
    assert "Analysis Phase Results" in response.content
    assert "Content Creation Phase" in response.content
    assert "Artificial Intelligence Market Trends" in response.content


def test_custom_execution_with_none_return(workflow_storage):
    """Test custom execution function that returns None."""

    def none_return_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> None:
        """Custom execution that returns None."""
        # Function that performs side effects but returns None
        pass

    workflow = Workflow(
        name="None Return Custom Execution",
        storage=workflow_storage,
        steps=none_return_execution,
    )

    response = workflow.run(message="None test")

    assert isinstance(response, WorkflowRunResponse)
    assert response.status == RunStatus.completed
    # Content might be empty or have a default message


def test_custom_execution_with_empty_string_return(workflow_storage):
    """Test custom execution function that returns empty string."""

    def empty_string_execution(workflow: Workflow, execution_input: WorkflowExecutionInput) -> str:
        """Custom execution that returns empty string."""
        return ""

    workflow = Workflow(
        name="Empty String Custom Execution",
        storage=workflow_storage,
        steps=empty_string_execution,
    )

    response = workflow.run(message="Empty test")

    assert isinstance(response, WorkflowRunResponse)
    assert response.status == RunStatus.completed
    # Content should be empty string
    assert response.content == ""
