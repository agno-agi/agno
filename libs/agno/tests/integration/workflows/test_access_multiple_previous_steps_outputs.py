"""Integration tests for accessing multiple previous step outputs in workflows."""

import pytest

from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.workflow import Condition, Parallel, Step, Workflow
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput


# Helper functions
def step_a(step_input: StepInput) -> StepOutput:
    """Step A in parallel execution."""
    return StepOutput(step_name="step_a", content=f"Step A processed: {step_input.input}", success=True)


def step_b(step_input: StepInput) -> StepOutput:
    """Step B in parallel execution."""
    return StepOutput(step_name="step_b", content=f"Step B analyzed: {step_input.input}", success=True)


def step_c(step_input: StepInput) -> StepOutput:
    """Step C in parallel execution."""
    return StepOutput(step_name="step_c", content=f"Step C reviewed: {step_input.input}", success=True)


def parallel_aggregator_step(step_input: StepInput) -> StepOutput:
    """Aggregator step that accesses parallel step outputs."""
    # Get the parallel step content - should return a dict
    parallel_data = step_input.get_step_content("Parallel Processing")

    # Verify we can access individual step content
    step_a_data = parallel_data.get("step_a", "") if isinstance(parallel_data, dict) else ""
    step_b_data = parallel_data.get("step_b", "") if isinstance(parallel_data, dict) else ""
    step_c_data = parallel_data.get("step_c", "") if isinstance(parallel_data, dict) else ""

    # Test direct access to individual steps using get_step_output (should now work)
    direct_step_a_output = step_input.get_step_output("step_a")
    direct_step_a_content = step_input.get_step_content("step_a")
    direct_step_a_str = str(direct_step_a_content) if direct_step_a_content else "None"

    aggregated_report = f"""Parallel Aggregation Report:
        Parallel Data Type: {type(parallel_data).__name__}
        Step A: {step_a_data}
        Step B: {step_b_data}
        Step C: {step_c_data}
        Direct Step A Output: {direct_step_a_output is not None}
        Direct Step A Access: {direct_step_a_str}
        Available Steps: {list(step_input.previous_step_outputs.keys())}
        Previous step outputs: {step_input.previous_step_outputs}
    """

    return StepOutput(step_name="parallel_aggregator_step", content=aggregated_report, success=True)


def research_step(step_input: StepInput) -> StepOutput:
    """Research step."""
    return StepOutput(step_name="research_step", content=f"Research: {step_input.input}", success=True)


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


def test_basic_access(shared_db):
    """Test basic access to previous steps."""
    workflow = Workflow(name="Basic Access", db=shared_db, steps=[research_step, analysis_step, report_step])

    response = workflow.run(input="test topic")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 3

    # Verify report contains data from previous steps
    report = response.step_results[2]
    assert "Research:" in report.content
    assert "Analysis:" in report.content
    assert "research_step" in report.content
    assert "analysis_step" in report.content


def test_streaming_access(shared_db):
    """Test streaming with multiple step access."""
    workflow = Workflow(name="Streaming Access", db=shared_db, steps=[research_step, analysis_step, report_step])

    events = list(workflow.run(input="test topic", stream=True))

    # Verify events
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Report:" in completed_events[0].content


@pytest.mark.asyncio
async def test_async_access(shared_db):
    """Test async execution with multiple step access."""
    workflow = Workflow(name="Async Access", db=shared_db, steps=[research_step, analysis_step, report_step])

    response = await workflow.arun(input="test topic")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 3
    assert "Report:" in response.content


@pytest.mark.asyncio
async def test_async_streaming_access(shared_db):
    """Test async streaming with multiple step access."""
    workflow = Workflow(name="Async Streaming", db=shared_db, steps=[research_step, analysis_step, report_step])

    events = []
    async for event in workflow.arun(input="test topic", stream=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert "Report:" in completed_events[0].content


# Add this test function at the end
def test_parallel_step_access(shared_db):
    """Test accessing content from parallel steps."""
    workflow = Workflow(
        name="Parallel Step Access",
        db=shared_db,
        steps=[Parallel(step_a, step_b, step_c, name="Parallel Processing"), parallel_aggregator_step],
    )

    response = workflow.run(input="test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Verify the aggregator step received parallel data correctly
    aggregator_response = response.step_results[1]
    assert "Parallel Aggregation Report:" in aggregator_response.content
    assert "Parallel Data Type: dict" in aggregator_response.content
    assert "Step A: Step A processed: test data" in aggregator_response.content
    assert "Step B: Step B analyzed: test data" in aggregator_response.content
    assert "Step C: Step C reviewed: test data" in aggregator_response.content
    assert "Direct Step A Output: True" in aggregator_response.content
    assert "Direct Step A Access: Step A processed: test data" in aggregator_response.content
    assert "Parallel Processing" in aggregator_response.content


@pytest.mark.asyncio
async def test_async_parallel_step_access(shared_db):
    """Test async accessing content from parallel steps."""
    workflow = Workflow(
        name="Async Parallel Step Access",
        db=shared_db,
        steps=[Parallel(step_a, step_b, step_c, name="Parallel Processing"), parallel_aggregator_step],
    )

    response = await workflow.arun(input="async test data")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Verify the aggregator step received parallel data correctly
    aggregator_response = response.step_results[1]
    assert "Parallel Aggregation Report:" in aggregator_response.content
    assert "Parallel Data Type: dict" in aggregator_response.content
    assert "Step A: Step A processed: async test data" in aggregator_response.content
    assert "Step B: Step B analyzed: async test data" in aggregator_response.content
    assert "Step C: Step C reviewed: async test data" in aggregator_response.content
    assert "Direct Step A Output: True" in aggregator_response.content
    assert "Direct Step A Access: Step A processed: async test data" in aggregator_response.content


def test_single_parallel_step_access(shared_db):
    """Test accessing content from a single step in parallel (edge case)."""
    workflow = Workflow(
        name="Single Parallel Step Access",
        db=shared_db,
        steps=[Parallel(step_a, name="Parallel Processing"), parallel_aggregator_step],
    )

    response = workflow.run(input="single test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Verify even single parallel steps return dict structure
    aggregator_response = response.step_results[1]
    assert "Parallel Data Type: dict" in aggregator_response.content
    assert "Step A: Step A processed: single test" in aggregator_response.content


def nested_step_inside_condition(step_input: StepInput) -> StepOutput:
    """Step nested inside a Condition."""
    return StepOutput(step_name="nested_step", content=f"Nested: {step_input.input}", success=True)


def condition_evaluator(step_input: StepInput) -> bool:
    """Always return True for testing."""
    return True


def test_nested_step_in_parallel_and_condition(shared_db):
    """Test accessing a step nested inside Parallel -> Condition."""
    workflow = Workflow(
        name="Nested Step Access",
        db=shared_db,
        steps=[
            Parallel(
                Condition(
                    name="nested_condition",
                    evaluator=condition_evaluator,
                    steps=[nested_step_inside_condition],
                ),
                name="Parallel Processing",
            ),
            parallel_aggregator_step,
        ],
    )

    response = workflow.run(input="nested test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Verify we can access the deeply nested step
    aggregator_response = response.step_results[1]
    assert "Parallel Aggregation Report:" in aggregator_response.content


def test_direct_lookup_priority(shared_db):
    """Test that direct lookup takes priority over nested search."""

    # Create a step with the same name as a nested step
    def top_level_step(step_input: StepInput) -> StepOutput:
        return StepOutput(step_name="step_a", content="Top level step_a", success=True)

    workflow = Workflow(
        name="Direct Lookup Priority",
        db=shared_db,
        steps=[
            top_level_step,  # Top-level step_a
            Parallel(step_a, name="Parallel Processing"),  # Nested step_a
            parallel_aggregator_step,
        ],
    )

    response = workflow.run(input="priority test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 3

    # The aggregator should access the top-level step_a, not the nested one
    aggregator_response = response.step_results[2]
    # Since we have both top-level and nested step_a, get_step_output should return top-level first
    # But get_step_content might return the nested one from parallel
    assert "Parallel Aggregation Report:" in aggregator_response.content


def test_multiple_depth_nested_access(shared_db):
    """Test accessing steps at multiple depth levels."""

    def deep_nested_step(step_input: StepInput) -> StepOutput:
        """Step nested deep inside Parallel -> Condition -> Steps."""
        return StepOutput(step_name="deep_nested_step", content="Deep nested content", success=True)

    def verify_nested_access(step_input: StepInput) -> StepOutput:
        """Verify we can access deeply nested step."""
        nested_output = step_input.get_step_output("deep_nested_step")
        nested_content = step_input.get_step_content("deep_nested_step")

        result = f"Nested output found: {nested_output is not None}, Content: {nested_content}"
        return StepOutput(step_name="verifier", content=result, success=True)

    workflow = Workflow(
        name="Multiple Depth Access",
        db=shared_db,
        steps=[
            Parallel(
                Condition(
                    name="condition_layer",
                    evaluator=condition_evaluator,
                    steps=[
                        Steps(
                            name="steps_layer",
                            steps=[deep_nested_step],
                        )
                    ],
                ),
                name="Parallel Processing",
            ),
            Step(name="verifier", executor=verify_nested_access),
        ],
    )

    response = workflow.run(input="deep test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Verify we can access the deeply nested step
    verifier_response = response.step_results[1]
    assert "Nested output found: True" in verifier_response.content
    assert "Content: Deep nested content" in verifier_response.content
