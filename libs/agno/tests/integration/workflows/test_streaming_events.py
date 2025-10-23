"""Integration tests for workflow streaming events."""

from typing import List

import pytest

from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    StepCompletedEvent,
    StepOutputEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput


# Helper functions for testing
def step_function(step_input: StepInput) -> StepOutput:
    """Basic step function."""
    return StepOutput(content=f"Step output: {step_input.input}")


def simple_step_1(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Step 1 completed")


def simple_step_2(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Step 2 completed")


def condition_check(step_input: StepInput) -> bool:
    """Simple condition check."""
    return "test" in str(step_input.input)


def loop_condition(outputs):
    """Loop end condition."""
    return len(outputs) >= 2


def router_function(step_input: StepInput) -> List[Step]:
    """Router function to select steps."""
    if "a" in str(step_input.input):
        return [Step(name="route_a", executor=step_a)]
    else:
        return [Step(name="route_b", executor=step_b)]


def simple_router(step_input: StepInput) -> list:
    return [Step(name="routed_step", executor=simple_step_1)]


def step_a(step_input: StepInput) -> StepOutput:
    """Step A for router."""
    return StepOutput(content="Step A executed")


def step_b(step_input: StepInput) -> StepOutput:
    """Step B for router."""
    return StepOutput(content="Step B executed")


# ============================================================================
# STEP EVENTS TESTS
# ============================================================================


def test_step_events_with_stream_events_false(shared_db):
    """Test Step events with stream_events=False."""
    workflow = Workflow(
        name="Step Events Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=step_function)],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events, NO step started/completed events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types


def test_step_events_with_stream_events_true(shared_db):
    """Test Step events with stream_events=True."""
    workflow = Workflow(
        name="Step Events Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=step_function)],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Check for step events
    step_started = [e for e in events if isinstance(e, StepStartedEvent)]
    step_completed = [e for e in events if isinstance(e, StepCompletedEvent)]
    workflow_started = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(step_started) == 1
    assert len(step_completed) == 1
    assert len(workflow_started) == 1
    assert len(workflow_completed) == 1

    # Verify event details
    assert step_started[0].step_name == "test_step"
    assert step_completed[0].step_name == "test_step"


def test_workflow_events_with_stream_events_false(shared_db):
    """Test that with stream_events=False, only workflow and content events are received."""
    workflow = Workflow(
        name="Test Workflow",
        steps=[
            Step(name="step_1", executor=simple_step_1),
            Step(name="step_2", executor=simple_step_2),
        ],
        db=shared_db,
    )

    events = list(workflow.run(input="test message", stream=True, stream_events=False))

    # Extract event types
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events and step outputs, NO step started/completed events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types

    # Should have step outputs from the function executors
    step_outputs = [event for event in events if isinstance(event, StepOutputEvent)]
    assert len(step_outputs) == 2
    assert step_outputs[0].content == "Step 1 completed"
    assert step_outputs[1].content == "Step 2 completed"


def test_workflow_events_with_stream_events_true(shared_db):
    """Test that with stream_events=True, all events including step events are received."""
    workflow = Workflow(
        name="Test Workflow",
        steps=[
            Step(name="step_1", executor=simple_step_1),
            Step(name="step_2", executor=simple_step_2),
        ],
        db=shared_db,
    )

    events = list(workflow.run(input="test message", stream=True, stream_events=True))

    # Extract event types
    event_types = [type(event).__name__ for event in events]

    # Should have all workflow and step events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types

    # Should have step outputs
    step_outputs = [event for event in events if isinstance(event, StepOutputEvent)]
    assert len(step_outputs) == 2

    # Verify step events are properly paired
    step_started_events = [event for event in events if isinstance(event, StepStartedEvent)]
    step_completed_events = [event for event in events if isinstance(event, StepCompletedEvent)]
    assert len(step_started_events) == 2
    assert len(step_completed_events) == 2


@pytest.mark.asyncio
async def test_step_events_async_with_stream_events_true(shared_db):
    """Test Step events in async streaming with stream_events=True."""
    workflow = Workflow(
        name="Async Step Events Test",
        db=shared_db,
        steps=[Step(name="test_step", executor=step_function)],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Check for step events
    step_started = [e for e in events if isinstance(e, StepStartedEvent)]
    step_completed = [e for e in events if isinstance(e, StepCompletedEvent)]
    workflow_started = [e for e in events if isinstance(e, WorkflowStartedEvent)]
    workflow_completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]

    assert len(step_started) == 1
    assert len(step_completed) == 1
    assert len(workflow_started) == 1
    assert len(workflow_completed) == 1


# ============================================================================
# STEPS EVENTS TESTS
# ============================================================================


def test_steps_events_with_stream_events_false(shared_db):
    """Test Steps events with stream_events=False."""
    workflow = Workflow(
        name="Steps Events Test",
        db=shared_db,
        steps=[
            Steps(
                name="test_steps",
                steps=[
                    Step(name="step1", executor=step_function),
                    Step(name="step2", executor=step_function),
                ],
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepsExecutionStartedEvent" not in event_types
    assert "StepsExecutionCompletedEvent" not in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types


def test_steps_events_with_stream_events_true(shared_db):
    """Test Steps events with stream_events=True."""
    workflow = Workflow(
        name="Steps Events Test",
        db=shared_db,
        steps=[
            Steps(
                name="test_steps",
                steps=[
                    Step(name="step1", executor=step_function),
                    Step(name="step2", executor=step_function),
                ],
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Check for steps events
    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]

    assert len(steps_started) == 1
    assert len(steps_completed) == 1

    # Verify event details
    assert steps_started[0].step_name == "test_steps"
    assert steps_completed[0].step_name == "test_steps"


@pytest.mark.asyncio
async def test_steps_events_async_with_stream_events_true(shared_db):
    """Test Steps events in async streaming with stream_events=True."""
    workflow = Workflow(
        name="Async Steps Events Test",
        db=shared_db,
        steps=[
            Steps(
                name="test_steps",
                steps=[
                    Step(name="step1", executor=step_function),
                    Step(name="step2", executor=step_function),
                ],
            )
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Check for steps events
    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]

    assert len(steps_started) == 1
    assert len(steps_completed) == 1


# ============================================================================
# PARALLEL EVENTS TESTS
# ============================================================================


def test_parallel_events_with_stream_events_false(shared_db):
    """Test Parallel events with stream_events=False."""
    workflow = Workflow(
        name="Parallel Events Test",
        db=shared_db,
        steps=[
            Parallel(
                step_a,
                step_b,
                name="test_parallel",
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events, NO parallel intermediate events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "ParallelExecutionStartedEvent" not in event_types
    assert "ParallelExecutionCompletedEvent" not in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types


def test_parallel_events_with_stream_events_true(shared_db):
    """Test Parallel events with stream_events=True."""
    workflow = Workflow(
        name="Parallel Events Test",
        db=shared_db,
        steps=[
            Parallel(
                step_a,
                step_b,
                name="test_parallel",
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Check for parallel events
    parallel_started = [e for e in events if isinstance(e, ParallelExecutionStartedEvent)]
    parallel_completed = [e for e in events if isinstance(e, ParallelExecutionCompletedEvent)]

    assert len(parallel_started) == 1
    assert len(parallel_completed) == 1

    # Verify event details
    assert parallel_started[0].step_name == "test_parallel"
    assert parallel_completed[0].step_name == "test_parallel"
    assert parallel_started[0].parallel_step_count == 2


@pytest.mark.asyncio
async def test_parallel_events_async_with_stream_events_true(shared_db):
    """Test Parallel events in async streaming with stream_events=True."""
    workflow = Workflow(
        name="Async Parallel Events Test",
        db=shared_db,
        steps=[
            Parallel(
                step_a,
                step_b,
                name="test_parallel",
            )
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Check for parallel events
    parallel_started = [e for e in events if isinstance(e, ParallelExecutionStartedEvent)]
    parallel_completed = [e for e in events if isinstance(e, ParallelExecutionCompletedEvent)]

    assert len(parallel_started) == 1
    assert len(parallel_completed) == 1


# ============================================================================
# LOOP EVENTS TESTS
# ============================================================================


def test_loop_events_with_stream_events_false(shared_db):
    """Test Loop events with stream_events=False."""
    workflow = Workflow(
        name="Loop Events Test",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=loop_condition,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events, NO loop intermediate events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "LoopExecutionStartedEvent" not in event_types
    assert "LoopExecutionCompletedEvent" not in event_types
    assert "LoopIterationStartedEvent" not in event_types
    assert "LoopIterationCompletedEvent" not in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types


def test_loop_events_with_stream_events_true(shared_db):
    """Test Loop events with stream_events=True."""
    workflow = Workflow(
        name="Loop Events Test",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=loop_condition,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Check for loop events
    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
    iteration_started = [e for e in events if isinstance(e, LoopIterationStartedEvent)]
    iteration_completed = [e for e in events if isinstance(e, LoopIterationCompletedEvent)]

    assert len(loop_started) == 1
    assert len(loop_completed) == 1
    assert len(iteration_started) >= 1
    assert len(iteration_completed) >= 1

    # Verify event details
    assert loop_started[0].step_name == "test_loop"
    assert loop_started[0].max_iterations == 3


@pytest.mark.asyncio
async def test_loop_events_async_with_stream_events_true(shared_db):
    """Test Loop events in async streaming with stream_events=True."""
    workflow = Workflow(
        name="Async Loop Events Test",
        db=shared_db,
        steps=[
            Loop(
                name="test_loop",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=loop_condition,
                max_iterations=3,
            )
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Check for loop events
    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]

    assert len(loop_started) == 1
    assert len(loop_completed) == 1


# ============================================================================
# CONDITION EVENTS TESTS
# ============================================================================


def test_condition_events_with_stream_events_false(shared_db):
    """Test Condition events with stream_events=False."""
    workflow = Workflow(
        name="Condition Events Test",
        db=shared_db,
        steps=[
            Condition(
                name="test_condition",
                evaluator=condition_check,
                steps=[Step(name="true_step", executor=step_function)],
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events, NO condition intermediate events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "ConditionExecutionStartedEvent" not in event_types
    assert "ConditionExecutionCompletedEvent" not in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types


def test_condition_events_with_stream_events_true(shared_db):
    """Test Condition events with stream_events=True."""
    workflow = Workflow(
        name="Condition Events Test",
        db=shared_db,
        steps=[
            Condition(
                name="test_condition",
                evaluator=condition_check,
                steps=[Step(name="true_step", executor=step_function)],
            )
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Check for condition events
    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1

    # Verify event details
    assert condition_started[0].step_name == "test_condition"
    assert condition_started[0].condition_result  # "test" in message


@pytest.mark.asyncio
async def test_condition_events_async_with_stream_events_true(shared_db):
    """Test Condition events in async streaming with stream_events=True."""
    workflow = Workflow(
        name="Async Condition Events Test",
        db=shared_db,
        steps=[
            Condition(
                name="test_condition",
                evaluator=condition_check,
                steps=[Step(name="true_step", executor=step_function)],
            )
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Check for condition events
    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(condition_started) == 1
    assert len(condition_completed) == 1


# ============================================================================
# ROUTER EVENTS TESTS
# ============================================================================


def test_router_events_with_stream_events_false(shared_db):
    """Test Router events with stream_events=False."""
    workflow = Workflow(
        name="Router Events Test",
        db=shared_db,
        steps=[
            Router(
                name="test_router",
                selector=router_function,
                choices=[
                    Step(name="route_a", executor=step_a),
                    Step(name="route_b", executor=step_b),
                ],
            )
        ],
    )

    events = list(workflow.run(input="test_a", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events, NO router intermediate events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "RouterExecutionStartedEvent" not in event_types
    assert "RouterExecutionCompletedEvent" not in event_types
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types


def test_router_events_with_stream_events_true(shared_db):
    """Test Router events with stream_events=True."""
    # Create the available choices
    route_a_step = Step(name="route_a", executor=step_a)
    route_b_step = Step(name="route_b", executor=step_b)

    workflow = Workflow(
        name="Router Events Test",
        db=shared_db,
        steps=[
            Router(
                name="test_router",
                selector=router_function,
                choices=[route_a_step, route_b_step],
            )
        ],
    )

    events = list(workflow.run(input="test_a", stream=True, stream_events=True))

    # Check for router events
    router_started = [e for e in events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]

    assert len(router_started) == 1
    assert len(router_completed) == 1

    # Verify event details
    assert router_started[0].step_name == "test_router"
    assert "route_a" in router_started[0].selected_steps


@pytest.mark.asyncio
async def test_router_events_async_with_stream_events_true(shared_db):
    """Test Router events in async streaming with stream_events=True."""
    # Create the available choices
    route_a_step = Step(name="route_a", executor=step_a)
    route_b_step = Step(name="route_b", executor=step_b)

    workflow = Workflow(
        name="Async Router Events Test",
        db=shared_db,
        steps=[
            Router(
                name="test_router",
                selector=router_function,
                choices=[route_a_step, route_b_step],
            )
        ],
    )

    events = []
    async for event in workflow.arun(input="test_a", stream=True, stream_events=True):
        events.append(event)

    # Check for router events
    router_started = [e for e in events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]

    assert len(router_started) == 1
    assert len(router_completed) == 1


# ============================================================================
# COMPREHENSIVE WORKFLOW TESTS
# ============================================================================


def test_comprehensive_workflow_events_with_stream_events_true(shared_db):
    """Test comprehensive workflow with multiple component types with stream_events=True."""
    workflow = Workflow(
        name="Comprehensive Events Test",
        db=shared_db,
        steps=[
            Step(name="initial_step", executor=step_function),
            Parallel(
                step_a,
                step_b,
                name="parallel_phase",
            ),
            Loop(
                name="loop_phase",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=lambda outputs: len(outputs) >= 1,
                max_iterations=2,
            ),
            Condition(
                name="condition_phase",
                evaluator=condition_check,
                steps=[Step(name="final_step", executor=step_function)],
            ),
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=True))

    # Check that we have events from all components
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    parallel_events = [
        e for e in events if isinstance(e, (ParallelExecutionStartedEvent, ParallelExecutionCompletedEvent))
    ]
    loop_events = [e for e in events if isinstance(e, (LoopExecutionStartedEvent, LoopExecutionCompletedEvent))]
    condition_events = [
        e for e in events if isinstance(e, (ConditionExecutionStartedEvent, ConditionExecutionCompletedEvent))
    ]
    workflow_events = [e for e in events if isinstance(e, (WorkflowStartedEvent, WorkflowCompletedEvent))]

    assert len(step_events) >= 4  # At least initial + final steps
    assert len(parallel_events) >= 2  # Started + completed
    assert len(loop_events) >= 2  # Started + completed
    assert len(condition_events) >= 2  # Started + completed
    assert len(workflow_events) == 2  # Started + completed


@pytest.mark.asyncio
async def test_comprehensive_workflow_events_async_with_stream_events_true(shared_db):
    """Test comprehensive workflow with multiple component types - async with stream_events=True."""
    workflow = Workflow(
        name="Async Comprehensive Events Test",
        db=shared_db,
        steps=[
            Step(name="initial_step", executor=step_function),
            Parallel(
                step_a,
                step_b,
                name="parallel_phase",
            ),
            Loop(
                name="loop_phase",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=lambda outputs: len(outputs) >= 1,
                max_iterations=2,
            ),
        ],
    )

    events = []
    async for event in workflow.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    # Check that we have events from all components
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    parallel_events = [
        e for e in events if isinstance(e, (ParallelExecutionStartedEvent, ParallelExecutionCompletedEvent))
    ]
    loop_events = [e for e in events if isinstance(e, (LoopExecutionStartedEvent, LoopExecutionCompletedEvent))]
    workflow_events = [e for e in events if isinstance(e, (WorkflowStartedEvent, WorkflowCompletedEvent))]

    assert len(step_events) >= 2  # At least initial step
    assert len(parallel_events) >= 2  # Started + completed
    assert len(loop_events) >= 2  # Started + completed
    assert len(workflow_events) == 2  # Started + completed


def test_comprehensive_workflow_events_with_stream_events_false(shared_db):
    """Test comprehensive workflow with multiple component types with stream_events=False."""
    workflow = Workflow(
        name="Comprehensive Events Test",
        db=shared_db,
        steps=[
            Step(name="initial_step", executor=step_function),
            Parallel(
                step_a,
                step_b,
                name="parallel_phase",
            ),
            Loop(
                name="loop_phase",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=lambda outputs: len(outputs) >= 1,
                max_iterations=2,
            ),
            Condition(
                name="condition_phase",
                evaluator=condition_check,
                steps=[Step(name="final_step", executor=step_function)],
            ),
        ],
    )

    events = list(workflow.run(input="test", stream=True, stream_events=False))
    event_types = [type(event).__name__ for event in events]

    # Should only have workflow events, NO intermediate component events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types

    # NO intermediate events should be present
    assert "StepStartedEvent" not in event_types
    assert "StepCompletedEvent" not in event_types
    assert "ParallelExecutionStartedEvent" not in event_types
    assert "ParallelExecutionCompletedEvent" not in event_types
    assert "LoopExecutionStartedEvent" not in event_types
    assert "LoopExecutionCompletedEvent" not in event_types
    assert "LoopIterationStartedEvent" not in event_types
    assert "LoopIterationCompletedEvent" not in event_types
    assert "ConditionExecutionStartedEvent" not in event_types
    assert "ConditionExecutionCompletedEvent" not in event_types

    # Should have workflow start/complete and step outputs only
    workflow_events = [e for e in events if isinstance(e, (WorkflowStartedEvent, WorkflowCompletedEvent))]
    step_outputs = [e for e in events if isinstance(e, StepOutputEvent)]

    assert len(workflow_events) == 2  # Started + completed
    assert len(step_outputs) >= 1  # At least one aggregated output from the workflow


# ============================================================================
# STREAM EXECUTOR EVENTS TESTS
# ============================================================================


def test_stream_executor_events_false_with_agent(shared_db, test_agent):
    """Test that stream_executor_events=False filters out agent internal events."""
    agent = test_agent

    workflow = Workflow(
        name="Executor Events Test",
        db=shared_db,
        steps=[Step(name="agent_step", agent=agent)],
        stream_executor_events=False,  # Filter out executor events
    )

    events = list(
        workflow.run(
            input="Say hello",
            stream=True,
            stream_events=True,
        )
    )

    event_types = [type(event).__name__ for event in events]

    # Should have workflow and step events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types

    # Should NOT have agent run events
    assert "RunContentEvent" not in event_types


def test_stream_executor_events_true_with_agent(shared_db, test_agent):
    """Test that stream_executor_events=True includes agent internal events."""
    agent = test_agent

    workflow = Workflow(
        name="Executor Events Test",
        db=shared_db,
        steps=[Step(name="agent_step", agent=agent)],
        stream_executor_events=True,  # Include executor events
    )

    events = list(
        workflow.run(
            input="Say hello",
            stream=True,
            stream_events=True,
        )
    )

    event_types = [type(event).__name__ for event in events]

    # Should have workflow and step events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types

    # Should also have agent internal events
    has_agent_events = any(event_type in event_types for event_type in ["RunContentEvent"])
    assert has_agent_events, "Expected at least some agent internal events when stream_executor_events=True"


@pytest.mark.asyncio
async def test_stream_executor_events_false_async_with_agent(shared_db, test_agent):
    """Test stream_executor_events=False in async context with agent."""
    agent = test_agent

    workflow = Workflow(
        name="Async Executor Events Test",
        db=shared_db,
        steps=[Step(name="agent_step", agent=agent)],
        stream_executor_events=False,  # Filter out executor events
    )

    events = []
    async for event in workflow.arun(
        input="Say hello",
        stream=True,
        stream_events=True,
    ):
        events.append(event)

    event_types = [type(event).__name__ for event in events]

    # Should have workflow and step events
    assert "WorkflowStartedEvent" in event_types
    assert "WorkflowCompletedEvent" in event_types
    assert "StepStartedEvent" in event_types
    assert "StepCompletedEvent" in event_types

    # Should NOT have agent internal events
    assert "RunContentEvent" not in event_types
