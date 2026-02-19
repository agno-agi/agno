"""Integration tests for Parallel steps functionality."""

import threading
from contextvars import ContextVar
from secrets import token_hex
from typing import Any, Dict, List, Optional, Type

import pytest
from pydantic import BaseModel

from agno.agent._run_options import ResolvedRunOptions
from agno.run.base import RunContext
from agno.run.workflow import (
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
)
from agno.workflow import Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput


def find_content_in_steps(step_output, search_text):
    """Recursively search for content in step output and its nested steps."""
    if search_text in step_output.content:
        return True
    if step_output.steps:
        return any(find_content_in_steps(nested_step, search_text) for nested_step in step_output.steps)
    return False


# Simple step functions for testing
def step_a(step_input: StepInput) -> StepOutput:
    """Test step A."""
    return StepOutput(content="Output A")


def step_b(step_input: StepInput) -> StepOutput:
    """Test step B."""
    return StepOutput(content="Output B")


def final_step(step_input: StepInput) -> StepOutput:
    """Combine previous outputs."""
    return StepOutput(content=f"Final: {step_input.get_all_previous_content()}")


# ============================================================================
# TESTS (Fast - No Workflow Overhead)
# ============================================================================


def test_parallel_direct_execute():
    """Test Parallel.execute() directly without workflow."""
    parallel = Parallel(step_a, step_b, name="Direct Parallel")
    step_input = StepInput(input="direct test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Direct Parallel"
    assert result.step_type == "Parallel"
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in result.content
    assert "Output A" in result.content
    assert "Output B" in result.content

    # The actual step outputs should be in the steps field
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Output A")
    assert find_content_in_steps(result, "Output B")


@pytest.mark.asyncio
async def test_parallel_direct_aexecute():
    """Test Parallel.aexecute() directly without workflow."""
    parallel = Parallel(step_a, step_b, name="Direct Async Parallel")
    step_input = StepInput(input="direct async test")

    result = await parallel.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Direct Async Parallel"
    assert result.step_type == "Parallel"
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in result.content
    assert "Output A" in result.content
    assert "Output B" in result.content

    # The actual step outputs should be in the steps field
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Output A")
    assert find_content_in_steps(result, "Output B")


def test_parallel_direct_execute_stream():
    """Test Parallel.execute_stream() directly without workflow."""
    from agno.run.workflow import ParallelExecutionCompletedEvent, ParallelExecutionStartedEvent, WorkflowRunOutput

    parallel = Parallel(step_a, step_b, name="Direct Stream Parallel")
    step_input = StepInput(input="direct stream test")

    # Mock workflow response for streaming
    mock_response = WorkflowRunOutput(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(parallel.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))

    # Should have started, completed events and final result
    started_events = [e for e in events if isinstance(e, ParallelExecutionStartedEvent)]
    completed_events = [e for e in events if isinstance(e, ParallelExecutionCompletedEvent)]
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert len(step_outputs) == 1
    assert started_events[0].parallel_step_count == 2

    # Check the parallel container output
    parallel_output = step_outputs[0]
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in parallel_output.content
    assert "Output A" in parallel_output.content
    assert "Output B" in parallel_output.content
    assert len(parallel_output.steps) == 2
    assert find_content_in_steps(parallel_output, "Output A")
    assert find_content_in_steps(parallel_output, "Output B")


def test_parallel_direct_single_step():
    """Test Parallel with single step."""
    parallel = Parallel(step_a, name="Single Step Parallel")
    step_input = StepInput(input="single test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.step_name == "Single Step Parallel"
    assert result.step_type == "Parallel"
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in result.content
    assert "Output A" in result.content

    # Single step should still be in the steps field
    assert len(result.steps) == 1
    assert result.steps[0].content == "Output A"


# ============================================================================
# CONTEXT PROPAGATION TESTS
# ============================================================================

# ContextVar for testing context propagation to child threads
_test_context_var: ContextVar[str] = ContextVar("test_context_var", default="not_set")


def _step_read_context(step_input: StepInput) -> StepOutput:
    """Step that reads a context variable to verify propagation."""
    value = _test_context_var.get()
    return StepOutput(content=f"context_value={value}")


def test_parallel_context_propagation():
    """Test that context variables are propagated to parallel step threads.

    This verifies that copy_context().run() is used when submitting tasks
    to the ThreadPoolExecutor, ensuring contextvars are available in child threads.
    """
    # Set context variable in main thread
    value = token_hex(16)
    token = _test_context_var.set(value)

    try:
        parallel = Parallel(
            _step_read_context,
            _step_read_context,
            name="Context Propagation Test",
        )
        step_input = StepInput(input="context test")

        result = parallel.execute(step_input)

        # Both parallel steps should have received the context variable
        assert len(result.steps) == 2
        for step_result in result.steps:
            assert f"context_value={value}" in step_result.content, (
                f"Context variable was not propagated to child thread. Got: {step_result.content}"
            )
    finally:
        _test_context_var.reset(token)


def test_parallel_context_propagation_streaming():
    """Test context propagation in streaming parallel execution."""
    from agno.run.workflow import WorkflowRunOutput

    value = token_hex(16)
    token = _test_context_var.set(value)

    try:
        parallel = Parallel(
            _step_read_context,
            _step_read_context,
            name="Context Stream Test",
        )
        step_input = StepInput(input="context stream test")

        mock_response = WorkflowRunOutput(
            run_id="test-run",
            workflow_name="test-workflow",
            workflow_id="test-id",
            session_id="test-session",
            content="",
        )

        events = list(parallel.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))
        step_outputs = [e for e in events if isinstance(e, StepOutput)]

        assert len(step_outputs) == 1
        parallel_output = step_outputs[0]
        assert len(parallel_output.steps) == 2

        for step_result in parallel_output.steps:
            assert f"context_value={value}" in step_result.content, (
                f"Context variable was not propagated in streaming mode. Got: {step_result.content}"
            )
    finally:
        _test_context_var.reset(token)


# ============================================================================
# INTEGRATION TESTS (With Workflow)
# ============================================================================


def test_basic_parallel(shared_db):
    """Test basic parallel execution."""
    workflow = Workflow(
        name="Basic Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Check parallel output
    parallel_output = response.step_results[0]
    assert isinstance(parallel_output, StepOutput)
    assert parallel_output.step_type == "Parallel"
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in parallel_output.content
    assert "Output A" in parallel_output.content
    assert "Output B" in parallel_output.content

    # The actual step outputs should be in the nested steps
    assert len(parallel_output.steps) == 2
    assert find_content_in_steps(parallel_output, "Output A")
    assert find_content_in_steps(parallel_output, "Output B")


def test_parallel_streaming(shared_db):
    """Test parallel execution with streaming."""
    workflow = Workflow(
        name="Streaming Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))
    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

    # Check that the parallel output has nested steps
    final_response = completed_events[0]
    parallel_output = final_response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2


def test_parallel_with_agent(shared_db, test_agent):
    """Test parallel execution with agent step."""
    agent_step = Step(name="agent_step", agent=test_agent)

    workflow = Workflow(
        name="Agent Parallel",
        db=shared_db,
        steps=[Parallel(step_a, agent_step, name="Mixed Parallel"), final_step],
    )

    response = workflow.run(input="test")
    assert isinstance(response, WorkflowRunOutput)
    parallel_output = response.step_results[0]
    assert isinstance(parallel_output, StepOutput)
    assert parallel_output.step_type == "Parallel"
    # Content should contain aggregated results from all inner steps
    assert "## Parallel Execution Results" in parallel_output.content
    assert "Output A" in parallel_output.content

    # Check nested steps contain both function and agent outputs
    assert len(parallel_output.steps) == 2
    assert find_content_in_steps(parallel_output, "Output A")
    # Agent output will vary, but should be present in nested steps


@pytest.mark.asyncio
async def test_async_parallel(shared_db):
    """Test async parallel execution."""
    workflow = Workflow(
        name="Async Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    response = await workflow.arun(input="test")
    assert isinstance(response, WorkflowRunOutput)
    assert len(response.step_results) == 2

    # Check parallel output structure
    parallel_output = response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2


@pytest.mark.asyncio
async def test_async_parallel_streaming(shared_db):
    """Test async parallel execution with streaming."""
    workflow = Workflow(
        name="Async Streaming Parallel",
        db=shared_db,
        steps=[Parallel(step_a, step_b, name="Parallel Phase"), final_step],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    completed_events = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].content is not None

    # Check parallel structure in final result
    final_response = completed_events[0]
    parallel_output = final_response.step_results[0]
    assert parallel_output.step_type == "Parallel"
    assert len(parallel_output.steps) == 2


# ============================================================================
# EARLY TERMINATION / STOP PROPAGATION TESTS
# ============================================================================


def early_stop_step(step_input: StepInput) -> StepOutput:
    """Step that requests early termination."""
    return StepOutput(
        content="Early stop requested",
        success=True,
        stop=True,
    )


def should_not_run_step(step_input: StepInput) -> StepOutput:
    """Step that should not run after early stop."""
    return StepOutput(
        content="This step should not have run",
        success=True,
    )


def normal_parallel_step(step_input: StepInput) -> StepOutput:
    """Normal step for parallel testing."""
    return StepOutput(
        content="Normal parallel step output",
        success=True,
    )


def test_parallel_propagates_stop_flag():
    """Test that Parallel propagates stop flag from any inner step."""
    parallel = Parallel(
        normal_parallel_step,
        early_stop_step,  # This step requests stop
        name="Stop Parallel",
    )
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Parallel should propagate stop=True from any inner step"


def test_parallel_stop_propagation_in_workflow(shared_db):
    """Test that workflow stops when Parallel's inner step returns stop=True."""
    workflow = Workflow(
        name="Parallel Stop Propagation Test",
        db=shared_db,
        steps=[
            Parallel(
                normal_parallel_step,
                early_stop_step,
                name="stop_parallel",
            ),
            should_not_run_step,  # This should NOT execute
        ],
    )

    response = workflow.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # Should only have 1 step result (the Parallel), not 2
    assert len(response.step_results) == 1, "Workflow should stop after Parallel with stop=True"
    assert response.step_results[0].stop is True


def test_parallel_streaming_propagates_stop(shared_db):
    """Test that streaming Parallel propagates stop flag and stops workflow."""
    workflow = Workflow(
        name="Streaming Parallel Stop Test",
        db=shared_db,
        steps=[
            Parallel(
                normal_parallel_step,
                early_stop_step,
                name="stop_parallel",
            ),
            should_not_run_step,
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Verify workflow completed
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(workflow_completed) == 1

    # Should only have 1 step result (the Parallel), not 2
    assert len(workflow_completed[0].step_results) == 1, "Workflow should stop after Parallel with stop=True"

    # Check that the parallel output has stop=True
    parallel_output = workflow_completed[0].step_results[0]
    assert parallel_output.stop is True

    # Check that at least one inner step has stop=True in results
    assert len(parallel_output.steps) == 2
    assert any(r.stop for r in parallel_output.steps), "At least one step should have stop=True"

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


@pytest.mark.asyncio
async def test_async_parallel_propagates_stop():
    """Test that async Parallel propagates stop flag."""
    parallel = Parallel(
        normal_parallel_step,
        early_stop_step,
        name="Async Stop Parallel",
    )
    step_input = StepInput(input="test")

    result = await parallel.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True, "Async Parallel should propagate stop=True from any inner step"


@pytest.mark.asyncio
async def test_async_parallel_streaming_propagates_stop(shared_db):
    """Test that async streaming Parallel propagates stop flag and stops workflow."""
    workflow = Workflow(
        name="Async Streaming Parallel Stop Test",
        db=shared_db,
        steps=[
            Parallel(
                normal_parallel_step,
                early_stop_step,
                name="stop_parallel",
            ),
            should_not_run_step,
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Verify workflow completed
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(workflow_completed) == 1

    # Should only have 1 step result (the Parallel), not 2
    assert len(workflow_completed[0].step_results) == 1, "Workflow should stop after Parallel with stop=True"

    # Check that the parallel output has stop=True
    parallel_output = workflow_completed[0].step_results[0]
    assert parallel_output.stop is True

    # Check that at least one inner step has stop=True in results
    assert len(parallel_output.steps) == 2
    assert any(r.stop for r in parallel_output.steps), "At least one step should have stop=True"

    # Most importantly: verify should_not_run_step was NOT executed
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    step_names = [e.step_name for e in step_events]
    assert "should_not_run_step" not in step_names, "Workflow should have stopped before should_not_run_step"


def test_parallel_all_steps_stop():
    """Test Parallel when all inner steps request stop."""

    def stop_step_1(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Stop 1", success=True, stop=True)

    def stop_step_2(step_input: StepInput) -> StepOutput:
        return StepOutput(content="Stop 2", success=True, stop=True)

    parallel = Parallel(
        stop_step_1,
        stop_step_2,
        name="All Stop Parallel",
    )
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is True
    assert len(result.steps) == 2
    assert all(step.stop for step in result.steps)


def test_parallel_no_stop():
    """Test Parallel when no inner steps request stop."""
    parallel = Parallel(
        normal_parallel_step,
        step_b,  # Using existing step_b from the file
        name="No Stop Parallel",
    )
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert result.stop is False, "Parallel should not set stop when no inner step requests it"


def test_parallel_name_as_first_positional_arg():
    """Test Parallel with name as first positional argument."""
    parallel = Parallel("My Named Parallel", step_a, step_b)
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name == "My Named Parallel"
    assert result.step_name == "My Named Parallel"
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Output A")
    assert find_content_in_steps(result, "Output B")


def test_parallel_name_as_keyword_arg():
    """Test Parallel with name as keyword argument (original behavior)."""
    parallel = Parallel(step_a, step_b, name="Keyword Named Parallel")
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name == "Keyword Named Parallel"
    assert result.step_name == "Keyword Named Parallel"
    assert len(result.steps) == 2
    assert find_content_in_steps(result, "Output A")
    assert find_content_in_steps(result, "Output B")


def test_parallel_no_name():
    """Test Parallel without any name."""
    parallel = Parallel(step_a, step_b)
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name is None
    assert result.step_name == "Parallel"  # Default name
    assert len(result.steps) == 2


def test_parallel_keyword_name_overrides_positional():
    """Test that keyword name takes precedence over positional name."""
    parallel = Parallel("Positional Name", step_a, step_b, name="Keyword Name")
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name == "Keyword Name"
    assert result.step_name == "Keyword Name"


def test_parallel_name_first_single_step():
    """Test Parallel with name first and single step."""
    parallel = Parallel("Single Step Named", step_a)
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name == "Single Step Named"
    assert len(result.steps) == 1
    assert find_content_in_steps(result, "Output A")


def test_parallel_name_first_with_description():
    """Test Parallel with name first and description as keyword."""
    parallel = Parallel("Described Parallel", step_a, step_b, description="A parallel with description")
    step_input = StepInput(input="test")

    result = parallel.execute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name == "Described Parallel"
    assert parallel.description == "A parallel with description"
    assert len(result.steps) == 2


@pytest.mark.asyncio
async def test_parallel_name_first_async():
    """Test async Parallel with name as first positional argument."""
    parallel = Parallel("Async Named Parallel", step_a, step_b)
    step_input = StepInput(input="test")

    result = await parallel.aexecute(step_input)

    assert isinstance(result, StepOutput)
    assert parallel.name == "Async Named Parallel"
    assert result.step_name == "Async Named Parallel"
    assert len(result.steps) == 2


def test_parallel_name_first_streaming():
    """Test streaming Parallel with name as first positional argument."""
    from agno.run.workflow import WorkflowRunOutput

    parallel = Parallel("Streaming Named Parallel", step_a, step_b)
    step_input = StepInput(input="test")

    mock_response = WorkflowRunOutput(
        run_id="test-run",
        workflow_name="test-workflow",
        workflow_id="test-id",
        session_id="test-session",
        content="",
    )

    events = list(parallel.execute_stream(step_input, workflow_run_response=mock_response, stream_events=True))
    step_outputs = [e for e in events if isinstance(e, StepOutput)]

    assert len(step_outputs) == 1
    assert parallel.name == "Streaming Named Parallel"
    assert step_outputs[0].step_name == "Streaming Named Parallel"


# ============================================================================
# OUTPUT SCHEMA ISOLATION TESTS (Regression: issue #6590)
# ============================================================================
# When parallel steps contain agents with different output_schema types, each
# step must receive its own run_context copy so that apply_to_context() writes
# do not clobber a sibling step's schema.


class ImageClassification(BaseModel):
    """Output schema for image classifier steps."""

    image_id: str
    category: str
    confidence: float
    tags: List[str]


class QualityAssessment(BaseModel):
    """Output schema for quality assessor steps."""

    image_id: str
    quality_score: int
    issues: List[str]
    approved: bool


def _make_schema_asserting_step(
    name: str,
    agent_output_schema: Type[BaseModel],
    captured: Dict[str, Any],
    barrier: threading.Barrier,
) -> Step:
    """Return a Step whose executor reproduces the apply_to_context race.

    The executor mirrors what Agent.run() does:
    1. Calls ResolvedRunOptions.apply_to_context() to write its schema onto the
       run_context it received (this is the mutation that caused the race).
    2. Waits at the barrier so all threads overlap at the mutation point —
       maximising the chance of observing cross-contamination on unfixed code.
    3. Reads back run_context.output_schema and records it.
    """

    def executor(
        step_input: StepInput,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Any = None,
        store_executor_outputs: bool = True,
        workflow_session: Any = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        background_tasks: Any = None,
    ) -> StepOutput:
        opts = ResolvedRunOptions(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            add_history_to_context=False,
            add_dependencies_to_context=False,
            add_session_state_to_context=False,
            dependencies=None,
            knowledge_filters=None,
            metadata=None,
            output_schema=agent_output_schema,
        )
        if run_context is not None:
            opts.apply_to_context(run_context)

        # Force all threads to overlap here before reading back — this reliably
        # triggers the race condition on unpatched code.
        barrier.wait(timeout=5)

        captured[name] = run_context.output_schema if run_context else None
        return StepOutput(step_name=name, content=f"{name} done")

    return Step(name=name, description=f"Schema isolation test: {name}", executor=executor)


def test_parallel_output_schema_no_cross_contamination():
    """Regression test for #6590: parallel steps with different output schemas must not interfere.

    Before the fix (PR #6609), all steps shared the same run_context object.
    Each step's apply_to_context() unconditionally overwrites run_context.output_schema,
    so concurrent writes would corrupt each other. The fix shallow-copies run_context
    per step so each step gets an isolated output_schema slot.
    """
    barrier = threading.Barrier(2)
    captured: Dict[str, Any] = {}

    classifier_step = _make_schema_asserting_step("classifier", ImageClassification, captured, barrier)
    qa_step = _make_schema_asserting_step("qa_assessor", QualityAssessment, captured, barrier)

    parallel = Parallel(classifier_step, qa_step, name="schema_isolation")
    run_context = RunContext(run_id="test-run", session_id="test-session")

    parallel.execute(StepInput(input="classify and assess img_001"), run_context=run_context)

    assert captured["classifier"] is ImageClassification, (
        f"classifier step got wrong schema: {captured['classifier']}"
    )
    assert captured["qa_assessor"] is QualityAssessment, (
        f"qa_assessor step got wrong schema: {captured['qa_assessor']}"
    )


def test_parallel_output_schema_isolation_three_steps():
    """Three concurrent steps with three distinct schemas — none must bleed into another."""

    class SchemaA(BaseModel):
        a: str

    class SchemaB(BaseModel):
        b: int

    class SchemaC(BaseModel):
        c: float

    barrier = threading.Barrier(3)
    captured: Dict[str, Any] = {}

    steps = [
        _make_schema_asserting_step("step_a", SchemaA, captured, barrier),
        _make_schema_asserting_step("step_b", SchemaB, captured, barrier),
        _make_schema_asserting_step("step_c", SchemaC, captured, barrier),
    ]

    parallel = Parallel(*steps, name="three_schema_isolation")
    run_context = RunContext(run_id="test-run-3", session_id="test-session-3")

    parallel.execute(StepInput(input="run all three"), run_context=run_context)

    assert captured["step_a"] is SchemaA
    assert captured["step_b"] is SchemaB
    assert captured["step_c"] is SchemaC


def test_parallel_does_not_mutate_caller_run_context():
    """Parallel execution must not mutate the caller's run_context.output_schema.

    Each step receives a shallow copy, so their apply_to_context() writes stay
    local and the original run_context is unchanged after execute() returns.
    """

    class CallerSchema(BaseModel):
        value: str

    class StepSchema(BaseModel):
        result: int

    barrier = threading.Barrier(2)
    captured: Dict[str, Any] = {}

    steps = [
        _make_schema_asserting_step("s1", StepSchema, captured, barrier),
        _make_schema_asserting_step("s2", StepSchema, captured, barrier),
    ]

    parallel = Parallel(*steps, name="immutable_ctx_test")
    run_context = RunContext(
        run_id="test-orig",
        session_id="test-orig-session",
        output_schema=CallerSchema,
    )

    parallel.execute(StepInput(input="test"), run_context=run_context)

    assert run_context.output_schema is CallerSchema, (
        f"Caller's run_context.output_schema was mutated: {run_context.output_schema}"
    )


def test_parallel_session_state_shared_across_steps():
    """session_state must remain shared (same dict object) after the shallow copy.

    The shallow copy isolates output_schema but preserves the session_state
    reference — mutations from one step are visible to all steps and to the caller.
    """
    shared_state: Dict[str, Any] = {"token": "shared_value"}
    state_ids: Dict[str, int] = {}
    barrier = threading.Barrier(2)

    def make_state_step(name: str) -> Step:
        def executor(
            step_input: StepInput,
            *,
            session_id: Optional[str] = None,
            user_id: Optional[str] = None,
            workflow_run_response: Any = None,
            store_executor_outputs: bool = True,
            workflow_session: Any = None,
            add_workflow_history_to_steps: Optional[bool] = False,
            num_history_runs: int = 3,
            run_context: Optional[RunContext] = None,
            session_state: Optional[Dict[str, Any]] = None,
            background_tasks: Any = None,
        ) -> StepOutput:
            if run_context is not None:
                state_ids[name] = id(run_context.session_state)
            barrier.wait(timeout=5)
            return StepOutput(step_name=name, content=f"{name} done")

        return Step(name=name, executor=executor)

    parallel = Parallel(make_state_step("p1"), make_state_step("p2"), name="session_state_sharing")
    run_context = RunContext(
        run_id="test-state",
        session_id="test-state-session",
        session_state=shared_state,
    )

    parallel.execute(StepInput(input="test"), run_context=run_context)

    assert state_ids["p1"] == state_ids["p2"], (
        "session_state should be the same dict object across parallel steps "
        f"(p1 id={state_ids['p1']}, p2 id={state_ids['p2']})"
    )
    assert state_ids["p1"] == id(shared_state), "session_state in steps should be the original shared dict"
