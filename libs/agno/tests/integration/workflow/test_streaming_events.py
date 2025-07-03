"""Integration tests for workflow streaming events."""

import pytest
from typing import List

from agno.run.v2.workflow import (
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
    StepStartedEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.workflow.v2 import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.v2.types import StepInput, StepOutput
from agno.utils.log import logger



# Helper functions for testing
def step_function(step_input: StepInput) -> StepOutput:
    """Basic step function."""
    return StepOutput(content=f"Step output: {step_input.message}")


def condition_check(step_input: StepInput) -> bool:
    """Simple condition check."""
    return "test" in str(step_input.message)


def loop_condition(outputs):
    """Loop end condition."""
    return len(outputs) >= 2


def router_function(step_input: StepInput) -> List[Step]:
    """Router function to select steps."""
    if "a" in str(step_input.message):
        return [Step(name="route_a", executor=step_a)]
    else:
        return [Step(name="route_b", executor=step_b)]


def step_a(step_input: StepInput) -> StepOutput:
    """Step A for router."""
    return StepOutput(content="Step A executed")


def step_b(step_input: StepInput) -> StepOutput:
    """Step B for router."""
    return StepOutput(content="Step B executed")


def test_step_events_sync(workflow_storage):
    """Test Step events in sync streaming."""
    workflow = Workflow(
        name="Step Events Test",
        storage=workflow_storage,
        steps=[Step(name="test_step", executor=step_function)],
    )

    events = list(workflow.run(message="test", stream=True))
    
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


@pytest.mark.asyncio
async def test_step_events_async(workflow_storage):
    """Test Step events in async streaming."""
    workflow = Workflow(
        name="Async Step Events Test",
        storage=workflow_storage,
        steps=[Step(name="test_step", executor=step_function)],
    )

    events = []
    async for event in await workflow.arun(message="test", stream=True):
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


def test_steps_events_sync(workflow_storage):
    """Test Steps events in sync streaming."""
    workflow = Workflow(
        name="Steps Events Test",
        storage=workflow_storage,
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

    events = list(workflow.run(message="test", stream=True))
    
    # Check for steps events
    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    
    assert len(steps_started) == 1
    assert len(steps_completed) == 1
    
    # Verify event details
    assert steps_started[0].step_name == "test_steps"
    assert steps_completed[0].step_name == "test_steps"


@pytest.mark.asyncio
async def test_steps_events_async(workflow_storage):
    """Test Steps events in async streaming."""
    workflow = Workflow(
        name="Async Steps Events Test",
        storage=workflow_storage,
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
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)
    
    # Check for steps events
    steps_started = [e for e in events if isinstance(e, StepsExecutionStartedEvent)]
    steps_completed = [e for e in events if isinstance(e, StepsExecutionCompletedEvent)]
    
    assert len(steps_started) == 1
    assert len(steps_completed) == 1


def test_parallel_events_sync(workflow_storage):
    """Test Parallel events in sync streaming."""
    workflow = Workflow(
        name="Parallel Events Test",
        storage=workflow_storage,
        steps=[
            Parallel(
                step_a,
                step_b,
                name="test_parallel",
            )
        ],
    )

    events = list(workflow.run(message="test", stream=True))
    
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
async def test_parallel_events_async(workflow_storage):
    """Test Parallel events in async streaming."""
    workflow = Workflow(
        name="Async Parallel Events Test",
        storage=workflow_storage,
        steps=[
            Parallel(
                step_a,
                step_b,
                name="test_parallel",
            )
        ],
    )

    events = []
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)
    
    # Check for parallel events
    parallel_started = [e for e in events if isinstance(e, ParallelExecutionStartedEvent)]
    parallel_completed = [e for e in events if isinstance(e, ParallelExecutionCompletedEvent)]
    
    assert len(parallel_started) == 1
    assert len(parallel_completed) == 1


def test_loop_events_sync(workflow_storage):
    """Test Loop events in sync streaming."""
    workflow = Workflow(
        name="Loop Events Test",
        storage=workflow_storage,
        steps=[
            Loop(
                name="test_loop",
                steps=[Step(name="loop_step", executor=step_function)],
                end_condition=loop_condition,
                max_iterations=3,
            )
        ],
    )

    events = list(workflow.run(message="test", stream=True))
    
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
async def test_loop_events_async(workflow_storage):
    """Test Loop events in async streaming."""
    workflow = Workflow(
        name="Async Loop Events Test",
        storage=workflow_storage,
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
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)
    
    # Check for loop events
    loop_started = [e for e in events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in events if isinstance(e, LoopExecutionCompletedEvent)]
    
    assert len(loop_started) == 1
    assert len(loop_completed) == 1


def test_condition_events_sync(workflow_storage):
    """Test Condition events in sync streaming."""
    workflow = Workflow(
        name="Condition Events Test",
        storage=workflow_storage,
        steps=[
            Condition(
                name="test_condition",
                evaluator=condition_check,
                steps=[Step(name="true_step", executor=step_function)],
            )
        ],
    )

    events = list(workflow.run(message="test", stream=True))
    
    # Check for condition events
    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    
    assert len(condition_started) == 1
    assert len(condition_completed) == 1
    
    # Verify event details
    assert condition_started[0].step_name == "test_condition"
    assert condition_started[0].condition_result == True  # "test" in message


@pytest.mark.asyncio
async def test_condition_events_async(workflow_storage):
    """Test Condition events in async streaming."""
    workflow = Workflow(
        name="Async Condition Events Test",
        storage=workflow_storage,
        steps=[
            Condition(
                name="test_condition",
                evaluator=condition_check,
                steps=[Step(name="true_step", executor=step_function)],
            )
        ],
    )

    events = []
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)
    
    # Check for condition events
    condition_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    condition_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]
    
    assert len(condition_started) == 1
    assert len(condition_completed) == 1


def test_router_events_sync(workflow_storage):
    """Test Router events in sync streaming."""
    # Create the available choices
    route_a_step = Step(name="route_a", executor=step_a)
    route_b_step = Step(name="route_b", executor=step_b)
    
    workflow = Workflow(
        name="Router Events Test",
        storage=workflow_storage,
        steps=[
            Router(
                name="test_router",
                selector=router_function,
                choices=[route_a_step, route_b_step],
            )
        ],
    )

    events = list(workflow.run(message="test_a", stream=True))
    
    # Check for router events
    router_started = [e for e in events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]
    
    assert len(router_started) == 1
    assert len(router_completed) == 1
    
    # Verify event details
    assert router_started[0].step_name == "test_router"
    assert "route_a" in router_started[0].selected_steps


@pytest.mark.asyncio
async def test_router_events_async(workflow_storage):
    """Test Router events in async streaming."""
    # Create the available choices
    route_a_step = Step(name="route_a", executor=step_a)
    route_b_step = Step(name="route_b", executor=step_b)
    
    workflow = Workflow(
        name="Async Router Events Test",
        storage=workflow_storage,
        steps=[
            Router(
                name="test_router",
                selector=router_function,
                choices=[route_a_step, route_b_step],
            )
        ],
    )

    events = []
    async for event in await workflow.arun(message="test_a", stream=True):
        events.append(event)
    
    # Check for router events
    router_started = [e for e in events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in events if isinstance(e, RouterExecutionCompletedEvent)]
    
    assert len(router_started) == 1
    assert len(router_completed) == 1


def test_comprehensive_workflow_events(workflow_storage):
    """Test comprehensive workflow with multiple component types."""
    workflow = Workflow(
        name="Comprehensive Events Test",
        storage=workflow_storage,
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

    events = list(workflow.run(message="test", stream=True))
    
    # Check that we have events from all components
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    parallel_events = [e for e in events if isinstance(e, (ParallelExecutionStartedEvent, ParallelExecutionCompletedEvent))]
    loop_events = [e for e in events if isinstance(e, (LoopExecutionStartedEvent, LoopExecutionCompletedEvent))]
    condition_events = [e for e in events if isinstance(e, (ConditionExecutionStartedEvent, ConditionExecutionCompletedEvent))]
    workflow_events = [e for e in events if isinstance(e, (WorkflowStartedEvent, WorkflowCompletedEvent))]
    
    assert len(step_events) >= 4  # At least initial + final steps
    assert len(parallel_events) >= 2  # Started + completed
    assert len(loop_events) >= 2  # Started + completed
    assert len(condition_events) >= 2  # Started + completed
    assert len(workflow_events) == 2  # Started + completed


@pytest.mark.asyncio
async def test_comprehensive_workflow_events_async(workflow_storage):
    """Test comprehensive workflow with multiple component types - async."""
    workflow = Workflow(
        name="Async Comprehensive Events Test",
        storage=workflow_storage,
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
    async for event in await workflow.arun(message="test", stream=True):
        events.append(event)
    
    # Check that we have events from all components
    step_events = [e for e in events if isinstance(e, (StepStartedEvent, StepCompletedEvent))]
    parallel_events = [e for e in events if isinstance(e, (ParallelExecutionStartedEvent, ParallelExecutionCompletedEvent))]
    loop_events = [e for e in events if isinstance(e, (LoopExecutionStartedEvent, LoopExecutionCompletedEvent))]
    workflow_events = [e for e in events if isinstance(e, (WorkflowStartedEvent, WorkflowCompletedEvent))]
    
    assert len(step_events) >= 2  # At least initial step
    assert len(parallel_events) >= 2  # Started + completed
    assert len(loop_events) >= 2  # Started + completed
    assert len(workflow_events) == 2  # Started + completed