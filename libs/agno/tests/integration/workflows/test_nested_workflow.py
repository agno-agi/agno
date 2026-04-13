"""Integration tests for nested workflow (workflow-as-a-step) functionality."""

import asyncio
from typing import List

import pytest

from agno.run.workflow import (
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
    WorkflowStartedEvent,
)
from agno.workflow import Condition, Loop, Parallel, Router, Step, StepInput, StepOutput, Workflow
from agno.workflow.types import StepType

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def step_a(step_input: StepInput) -> StepOutput:
    return StepOutput(content=f"StepA: {step_input.input}")


def step_b(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"StepB: {prev}")


def step_c(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"StepC: {prev}")


def summarize(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Summary: {prev[:100]}")


def always_true(step_input: StepInput) -> bool:
    return True


def always_false(step_input: StepInput) -> bool:
    return False


def loop_end_condition(outputs: List[StepOutput]) -> bool:
    return len(outputs) >= 1


def router_selector(step_input: StepInput) -> List[Step]:
    return [Step(name="route_a", executor=step_a)]


def error_step(step_input: StepInput) -> StepOutput:
    raise ValueError("Intentional error")


def stop_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Stopped", stop=True)


async def async_step_a(step_input: StepInput) -> StepOutput:
    await asyncio.sleep(0.001)
    return StepOutput(content=f"AsyncStepA: {step_input.input}")


async def async_step_b(step_input: StepInput) -> StepOutput:
    await asyncio.sleep(0.001)
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"AsyncStepB: {prev}")


# ============================================================================
# BASIC NESTED WORKFLOW TESTS
# ============================================================================


def test_basic_nested_workflow(shared_db):
    """Test basic nested workflow execution — sync non-streaming."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested_phase", workflow=inner),
            Step(name="final", executor=step_b),
        ],
    )

    response = outer.run(input="hello")

    assert isinstance(response, WorkflowRunOutput)
    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    # First result is the nested workflow step
    assert response.step_results[0].step_type == StepType.WORKFLOW
    assert response.step_results[0].executor_type == "workflow"
    assert response.step_results[0].executor_name == "Inner Workflow"
    assert "StepA: hello" in response.step_results[0].content
    # Second result chains from nested output
    assert "StepB:" in response.step_results[1].content


def test_nested_workflow_step_results_contain_inner_steps(shared_db):
    """Test that nested workflow's StepOutput contains inner step results."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Step(name="first_inner", executor=step_a),
            Step(name="second_inner", executor=step_b),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    response = outer.run(input="test")

    nested_output = response.step_results[0]
    assert nested_output.steps is not None
    assert len(nested_output.steps) == 2
    assert nested_output.steps[0].step_name == "first_inner"
    assert nested_output.steps[1].step_name == "second_inner"
    assert "StepA: test" in nested_output.steps[0].content
    assert "StepB: StepA: test" in nested_output.steps[1].content


def test_nested_workflow_content_chains_to_next_step(shared_db):
    """Test that nested workflow output chains correctly to the next step."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Step(name="produce", executor=lambda x: StepOutput(content="inner_result")),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="consumer", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert "StepB: inner_result" in response.step_results[1].content


def test_nested_workflow_success_flag(shared_db):
    """Test that nested workflow success is correctly propagated."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="ok_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    response = outer.run(input="test")

    assert response.step_results[0].success is True


# ============================================================================
# NESTED WORKFLOW WITH WORKFLOW PRIMITIVES
# ============================================================================


def test_nested_workflow_with_condition_inside(shared_db):
    """Test inner workflow containing a Condition step."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Condition(
                name="check",
                evaluator=always_true,
                steps=[Step(name="if_step", executor=lambda x: StepOutput(content="condition_met"))],
                else_steps=[Step(name="else_step", executor=lambda x: StepOutput(content="condition_not_met"))],
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert "condition_met" in response.step_results[0].content
    assert "StepB:" in response.step_results[1].content


def test_nested_workflow_with_loop_inside(shared_db):
    """Test inner workflow containing a Loop step."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Loop(
                name="repeat",
                steps=[Step(name="loop_step", executor=lambda x: StepOutput(content="looped"))],
                end_condition=loop_end_condition,
                max_iterations=2,
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    # Nested step should be a workflow type with loop output
    assert response.step_results[0].step_type == StepType.WORKFLOW
    assert response.step_results[0].executor_type == "workflow"
    assert "looped" in response.step_results[0].content
    # After step should chain from nested output
    assert "StepB:" in response.step_results[1].content


def test_nested_workflow_with_parallel_inside(shared_db):
    """Test inner workflow containing a Parallel step."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Parallel(
                Step(name="branch_a", executor=lambda x: StepOutput(content="A")),
                Step(name="branch_b", executor=lambda x: StepOutput(content="B")),
                name="parallel_step",
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    nested = response.step_results[0]
    assert nested.step_type == StepType.WORKFLOW
    assert nested.executor_type == "workflow"
    # Parallel output should contain results from both branches
    assert nested.content is not None
    assert nested.steps is not None
    # After step should receive content from nested
    assert "StepB:" in response.step_results[1].content


def test_nested_workflow_with_router_inside(shared_db):
    """Test inner workflow containing a Router step."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Router(
                name="route",
                selector=router_selector,
                choices=[
                    Step(name="route_a", executor=step_a),
                    Step(name="route_b", executor=step_b),
                ],
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    nested = response.step_results[0]
    assert nested.step_type == StepType.WORKFLOW
    assert nested.executor_type == "workflow"
    # Router should have selected route_a (our selector always returns route_a)
    assert "StepA:" in nested.content
    assert "StepB:" in response.step_results[1].content


# ============================================================================
# NESTED WORKFLOW INSIDE PRIMITIVES
# ============================================================================


def test_workflow_as_condition_step(shared_db):
    """Test using a workflow inside a Condition's steps."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Condition(
                name="cond",
                evaluator=always_true,
                steps=[Step(name="nested", workflow=inner)],
            ),
            Step(name="after", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) >= 2
    # The condition's nested workflow should have produced content with StepA
    assert "StepA:" in response.content or any("StepA:" in str(sr.content) for sr in response.step_results)
    # After step should have run
    assert any("StepB:" in str(sr.content) for sr in response.step_results)


def test_workflow_as_loop_step(shared_db):
    """Test using a workflow inside a Loop's steps."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Loop(
                name="loop",
                steps=[Step(name="nested", workflow=inner)],
                end_condition=loop_end_condition,
                max_iterations=1,
            ),
            Step(name="after", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) >= 2
    # After step should have received output from the loop
    assert any("StepB:" in str(sr.content) for sr in response.step_results)


def test_workflow_as_parallel_step(shared_db):
    """Test using two workflows inside a Parallel step, verifying both execute."""

    def set_key_a(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["key_a"] = "value_a"
        return StepOutput(content="from_A")

    def set_key_b(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["key_b"] = "value_b"
        return StepOutput(content="from_B")

    inner_a = Workflow(
        name="Inner A",
        steps=[Step(name="a_step", executor=set_key_a)],
    )
    inner_b = Workflow(
        name="Inner B",
        steps=[Step(name="b_step", executor=set_key_b)],
    )

    def read_keys(step_input: StepInput, session_state: dict) -> StepOutput:
        a = session_state.get("key_a", "MISSING")
        b = session_state.get("key_b", "MISSING")
        return StepOutput(content=f"a={a}, b={b}")

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Parallel(
                Step(name="nested_a", workflow=inner_a),
                Step(name="nested_b", workflow=inner_b),
                name="parallel_nested",
            ),
            Step(name="after", executor=read_keys),
        ],
    )

    response = outer.run(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) >= 2
    # Parallel output should contain results from both branches
    parallel_result = response.step_results[0]
    assert parallel_result.content is not None
    assert "from_A" in parallel_result.content
    assert "from_B" in parallel_result.content


# ============================================================================
# DEEPLY NESTED WORKFLOWS
# ============================================================================


def test_three_level_nested_workflow(shared_db):
    """Test workflow nested 3 levels deep."""
    level3 = Workflow(
        name="Level 3",
        steps=[Step(name="l3_step", executor=lambda x: StepOutput(content="level3_result"))],
    )

    level2 = Workflow(
        name="Level 2",
        steps=[
            Step(name="l2_nested", workflow=level3),
            Step(name="l2_step", executor=step_b),
        ],
    )

    level1 = Workflow(
        name="Level 1",
        db=shared_db,
        steps=[
            Step(name="l1_nested", workflow=level2),
            Step(name="l1_step", executor=step_c),
        ],
    )

    response = level1.run(input="deep_test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    # The chain should flow through all levels
    assert "StepC:" in response.step_results[1].content


# ============================================================================
# STREAMING TESTS
# ============================================================================


def test_nested_workflow_streaming_event_order_and_source(shared_db):
    """Test that streaming produces the correct event sequence with proper source tracking.

    Expected event order for: Outer[nested(Inner[inner_step, inner_summary]), final]
        1. WorkflowStartedEvent   (outer, depth=0)
        2. StepStartedEvent       (outer/nested, depth=0)
        3. WorkflowStartedEvent   (inner, depth=1)
        4. StepStartedEvent       (inner/inner_step, depth=1)
        5. StepCompletedEvent     (inner/inner_step, depth=1)
        6. StepStartedEvent       (inner/inner_summary, depth=1)
        7. StepCompletedEvent     (inner/inner_summary, depth=1)
        8. WorkflowCompletedEvent (inner, depth=1)
        9. StepCompletedEvent     (outer/nested, depth=0)
       10. StepStartedEvent       (outer/final, depth=0)
       11. StepCompletedEvent     (outer/final, depth=0)
       12. WorkflowCompletedEvent (outer, depth=0)
    """
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Step(name="inner_step", executor=step_a),
            Step(name="inner_summary", executor=summarize),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="final", executor=step_b),
        ],
    )

    all_events = list(outer.run(input="stream_test", stream=True, stream_events=True))

    # Filter to workflow-level events only
    tracked_types = (WorkflowStartedEvent, WorkflowCompletedEvent, StepStartedEvent, StepCompletedEvent)
    events = [e for e in all_events if isinstance(e, tracked_types)]

    # Should have exactly 12 events
    assert len(events) == 12, f"Expected 12 events, got {len(events)}: {[type(e).__name__ for e in events]}"

    # Verify event types in order
    expected_types = [
        WorkflowStartedEvent,  # 1. outer start
        StepStartedEvent,  # 2. outer/nested start
        WorkflowStartedEvent,  # 3. inner start
        StepStartedEvent,  # 4. inner/inner_step start
        StepCompletedEvent,  # 5. inner/inner_step complete
        StepStartedEvent,  # 6. inner/inner_summary start
        StepCompletedEvent,  # 7. inner/inner_summary complete
        WorkflowCompletedEvent,  # 8. inner complete
        StepCompletedEvent,  # 9. outer/nested complete
        StepStartedEvent,  # 10. outer/final start
        StepCompletedEvent,  # 11. outer/final complete
        WorkflowCompletedEvent,  # 12. outer complete
    ]
    for i, (ev, expected_type) in enumerate(zip(events, expected_types)):
        assert isinstance(ev, expected_type), (
            f"Event {i + 1}: expected {expected_type.__name__}, got {type(ev).__name__}"
        )

    # Verify depth for each event
    expected_depths = [0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0]
    for i, (ev, expected_depth) in enumerate(zip(events, expected_depths)):
        actual_depth = getattr(ev, "nested_depth", -1)
        assert actual_depth == expected_depth, (
            f"Event {i + 1} ({type(ev).__name__}): expected depth={expected_depth}, got {actual_depth}"
        )

    # Verify workflow_name for each event (inner events preserve inner workflow identity)
    expected_wf_names = [
        "Outer Workflow",  # 1
        "Outer Workflow",  # 2
        "Inner Workflow",  # 3
        "Inner Workflow",  # 4
        "Inner Workflow",  # 5
        "Inner Workflow",  # 6
        "Inner Workflow",  # 7
        "Inner Workflow",  # 8
        "Outer Workflow",  # 9
        "Outer Workflow",  # 10
        "Outer Workflow",  # 11
        "Outer Workflow",  # 12
    ]
    for i, (ev, expected_name) in enumerate(zip(events, expected_wf_names)):
        actual_name = getattr(ev, "workflow_name", None)
        assert actual_name == expected_name, (
            f"Event {i + 1} ({type(ev).__name__}): expected workflow_name='{expected_name}', got '{actual_name}'"
        )

    # Inner events preserve inner workflow_id, outer events have outer workflow_id
    for ev in events:
        if ev.workflow_name == "Inner Workflow":
            assert ev.workflow_id == "inner-workflow", "Inner events should preserve inner workflow_id"
        else:
            assert ev.workflow_id == "outer-workflow", "Outer events should have outer workflow_id"


def test_nested_workflow_streaming_with_loop_events(shared_db):
    """Test that Loop events inside a nested workflow get correct depth and source."""
    from agno.run.workflow import LoopExecutionCompletedEvent, LoopExecutionStartedEvent

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Loop(
                name="inner_loop",
                steps=[Step(name="loop_body", executor=lambda x: StepOutput(content="looped"))],
                end_condition=loop_end_condition,
                max_iterations=1,
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    all_events = list(outer.run(input="test", stream=True, stream_events=True))

    loop_started = [e for e in all_events if isinstance(e, LoopExecutionStartedEvent)]
    loop_completed = [e for e in all_events if isinstance(e, LoopExecutionCompletedEvent)]

    assert len(loop_started) >= 1, "Should have LoopExecutionStartedEvent"
    assert len(loop_completed) >= 1, "Should have LoopExecutionCompletedEvent"

    for ev in loop_started + loop_completed:
        assert ev.nested_depth == 1, f"Loop event depth should be 1, got {ev.nested_depth}"
        assert ev.workflow_name == "Inner Workflow"
        assert ev.workflow_id == "inner-workflow"


def test_nested_workflow_streaming_with_parallel_events(shared_db):
    """Test that Parallel events inside a nested workflow get correct depth and source."""
    from agno.run.workflow import ParallelExecutionCompletedEvent, ParallelExecutionStartedEvent

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Parallel(
                Step(name="branch_a", executor=lambda x: StepOutput(content="A")),
                Step(name="branch_b", executor=lambda x: StepOutput(content="B")),
                name="inner_parallel",
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    all_events = list(outer.run(input="test", stream=True, stream_events=True))

    par_started = [e for e in all_events if isinstance(e, ParallelExecutionStartedEvent)]
    par_completed = [e for e in all_events if isinstance(e, ParallelExecutionCompletedEvent)]

    assert len(par_started) >= 1, "Should have ParallelExecutionStartedEvent"
    assert len(par_completed) >= 1, "Should have ParallelExecutionCompletedEvent"

    for ev in par_started + par_completed:
        assert ev.nested_depth == 1, f"Parallel event depth should be 1, got {ev.nested_depth}"
        assert ev.workflow_name == "Inner Workflow"
        assert ev.workflow_id == "inner-workflow"


def test_nested_workflow_streaming_with_router_events(shared_db):
    """Test that Router events inside a nested workflow get correct depth and source."""
    from agno.run.workflow import RouterExecutionCompletedEvent, RouterExecutionStartedEvent

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Router(
                name="inner_router",
                selector=router_selector,
                choices=[
                    Step(name="route_a", executor=step_a),
                    Step(name="route_b", executor=step_b),
                ],
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    all_events = list(outer.run(input="test", stream=True, stream_events=True))

    router_started = [e for e in all_events if isinstance(e, RouterExecutionStartedEvent)]
    router_completed = [e for e in all_events if isinstance(e, RouterExecutionCompletedEvent)]

    assert len(router_started) >= 1, "Should have RouterExecutionStartedEvent"
    assert len(router_completed) >= 1, "Should have RouterExecutionCompletedEvent"

    for ev in router_started + router_completed:
        assert ev.nested_depth == 1, f"Router event depth should be 1, got {ev.nested_depth}"
        assert ev.workflow_name == "Inner Workflow"
        assert ev.workflow_id == "inner-workflow"


def test_nested_workflow_streaming_event_source_tracking(shared_db):
    """Test that workflow_id/name and nested_depth correctly identify inner vs outer events."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="final", executor=step_b),
        ],
    )

    events = list(outer.run(input="test", stream=True, stream_events=True))

    # Separate events by depth
    inner_events = [e for e in events if hasattr(e, "nested_depth") and getattr(e, "nested_depth", 0) > 0]
    outer_events = [
        e
        for e in events
        if hasattr(e, "nested_depth")
        and getattr(e, "nested_depth", 0) == 0
        and getattr(e, "workflow_id", None) is not None
    ]

    assert len(inner_events) > 0, "Should have inner workflow events with nested_depth > 0"
    assert len(outer_events) > 0, "Should have outer workflow events with nested_depth == 0"

    # Inner events: workflow_id/name preserved as inner, depth == 1
    for ev in inner_events:
        assert ev.workflow_name == "Inner Workflow", (
            f"Inner event should have workflow_name='Inner Workflow', got {ev.workflow_name}"
        )
        assert ev.workflow_id == "inner-workflow"
        assert ev.nested_depth == 1, f"Inner event depth should be 1, got {ev.nested_depth}"

    # Outer events: workflow_id/name points to outer, depth == 0
    for ev in outer_events:
        assert ev.workflow_name == "Outer Workflow"
        assert ev.workflow_id == "outer-workflow"
        assert ev.nested_depth == 0

    # Verify we have the right event types from inner workflow
    inner_step_started = [e for e in inner_events if isinstance(e, StepStartedEvent)]
    inner_step_completed = [e for e in inner_events if isinstance(e, StepCompletedEvent)]
    inner_wf_started = [e for e in inner_events if isinstance(e, WorkflowStartedEvent)]
    inner_wf_completed = [e for e in inner_events if isinstance(e, WorkflowCompletedEvent)]
    assert len(inner_step_started) >= 1, "Inner workflow should emit StepStartedEvent"
    assert len(inner_step_completed) >= 1, "Inner workflow should emit StepCompletedEvent"
    assert len(inner_wf_started) >= 1, "Inner workflow should emit WorkflowStartedEvent"
    assert len(inner_wf_completed) >= 1, "Inner workflow should emit WorkflowCompletedEvent"


def test_three_level_nested_depth_tracking(shared_db):
    """Test that nested_depth is correct for 3 levels of nesting."""
    level3 = Workflow(
        name="Level 3",
        steps=[Step(name="l3_step", executor=lambda x: StepOutput(content="l3"))],
    )

    level2 = Workflow(
        name="Level 2",
        steps=[Step(name="l2_nested", workflow=level3)],
    )

    level1 = Workflow(
        name="Level 1",
        db=shared_db,
        steps=[Step(name="l1_nested", workflow=level2)],
    )

    events = list(level1.run(input="test", stream=True, stream_events=True))

    # Categorize by workflow_name (preserved from originating workflow)
    l1_events = [e for e in events if getattr(e, "workflow_name", None) == "Level 1"]
    l2_events = [e for e in events if getattr(e, "workflow_name", None) == "Level 2"]
    l3_events = [e for e in events if getattr(e, "workflow_name", None) == "Level 3"]

    assert len(l1_events) > 0, "Should have Level 1 events"
    assert len(l2_events) > 0, "Should have Level 2 events"
    assert len(l3_events) > 0, "Should have Level 3 events"

    # Level 1 events: depth 0
    for ev in l1_events:
        assert ev.nested_depth == 0, f"Level 1 event depth should be 0, got {ev.nested_depth}"

    # Level 2 events: depth 1 (one level inside Level 1)
    for ev in l2_events:
        assert ev.nested_depth == 1, f"Level 2 event depth should be 1, got {ev.nested_depth}"

    # Level 3 events: depth 2 (two levels inside Level 1)
    for ev in l3_events:
        assert ev.nested_depth == 2, f"Level 3 event depth should be 2, got {ev.nested_depth}"


def test_nested_depth_with_condition_events(shared_db):
    """Test that Condition events inside a nested workflow get correct depth."""
    from agno.run.workflow import ConditionExecutionCompletedEvent, ConditionExecutionStartedEvent

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Step(name="pre", executor=step_a),
            Condition(
                name="inner_cond",
                evaluator=always_true,
                steps=[Step(name="if_step", executor=lambda x: StepOutput(content="cond_true"))],
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    events = list(outer.run(input="test", stream=True, stream_events=True))

    # Find condition events
    cond_started = [e for e in events if isinstance(e, ConditionExecutionStartedEvent)]
    cond_completed = [e for e in events if isinstance(e, ConditionExecutionCompletedEvent)]

    assert len(cond_started) >= 1, "Should have ConditionExecutionStartedEvent from inner workflow"
    assert len(cond_completed) >= 1, "Should have ConditionExecutionCompletedEvent from inner workflow"

    # Condition events from inner workflow should have depth 1
    for ev in cond_started + cond_completed:
        assert ev.nested_depth == 1, f"Condition event depth should be 1, got {ev.nested_depth}"
        assert ev.workflow_name == "Inner Workflow"


@pytest.mark.asyncio
async def test_async_nested_depth_tracking(shared_db):
    """Test that nested_depth works correctly in async streaming mode."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=async_step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="final", executor=async_step_b),
        ],
    )

    events = []
    async for event in outer.arun(input="test", stream=True, stream_events=True):
        events.append(event)

    inner_events = [e for e in events if hasattr(e, "nested_depth") and getattr(e, "nested_depth", 0) > 0]
    assert len(inner_events) > 0, "Async streaming should have inner events with depth > 0"

    for ev in inner_events:
        assert ev.workflow_name == "Inner Workflow"
        assert ev.nested_depth == 1


# ============================================================================
# ASYNC TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_async_nested_workflow(shared_db):
    """Test nested workflow execution — async non-streaming."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=async_step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="final", executor=async_step_b),
        ],
    )

    response = await outer.arun(input="async_test")

    assert isinstance(response, WorkflowRunOutput)
    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    assert response.step_results[0].step_type == StepType.WORKFLOW
    assert "AsyncStepA: async_test" in response.step_results[0].content


@pytest.mark.asyncio
async def test_async_nested_workflow_streaming(shared_db):
    """Test nested workflow execution — async streaming."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=async_step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="final", executor=async_step_b),
        ],
    )

    events = []
    async for event in outer.arun(input="async_stream", stream=True, stream_events=True):
        events.append(event)

    completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed) >= 2  # inner + outer


@pytest.mark.asyncio
async def test_async_nested_workflow_with_condition(shared_db):
    """Test async nested workflow containing a Condition step."""

    async def async_cond_step(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content="async_condition_met")

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Condition(
                name="cond",
                evaluator=always_true,
                steps=[Step(name="if_step", executor=async_cond_step)],
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=async_step_b),
        ],
    )

    response = await outer.arun(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    assert response.step_results[0].step_type == StepType.WORKFLOW
    assert "async_condition_met" in response.step_results[0].content


@pytest.mark.asyncio
async def test_async_nested_workflow_with_loop(shared_db):
    """Test async nested workflow containing a Loop step."""

    async def async_loop_body(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content="async_looped")

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Loop(
                name="loop",
                steps=[Step(name="loop_step", executor=async_loop_body)],
                end_condition=loop_end_condition,
                max_iterations=1,
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=async_step_b),
        ],
    )

    response = await outer.arun(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    assert response.step_results[0].step_type == StepType.WORKFLOW
    assert "async_looped" in response.step_results[0].content


@pytest.mark.asyncio
async def test_async_nested_workflow_with_parallel(shared_db):
    """Test async nested workflow containing a Parallel step."""

    async def async_branch_a(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content="async_A")

    async def async_branch_b(step_input: StepInput) -> StepOutput:
        await asyncio.sleep(0.001)
        return StepOutput(content="async_B")

    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Parallel(
                Step(name="branch_a", executor=async_branch_a),
                Step(name="branch_b", executor=async_branch_b),
                name="parallel",
            ),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=async_step_b),
        ],
    )

    response = await outer.arun(input="test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    nested = response.step_results[0]
    assert nested.step_type == StepType.WORKFLOW
    assert nested.content is not None


@pytest.mark.asyncio
async def test_async_nested_workflow_serialization(shared_db):
    """Test that async nested workflow output serializes correctly."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=async_step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    response = await outer.arun(input="test")

    response_dict = response.to_dict()
    assert response_dict["status"] == "COMPLETED"
    assert len(response_dict["step_results"]) == 1
    assert response_dict["step_results"][0]["executor_type"] == "workflow"

    restored = WorkflowRunOutput.from_dict(response_dict)
    status_val = restored.status.value if hasattr(restored.status, "value") else restored.status
    assert status_val == "COMPLETED"


@pytest.mark.asyncio
async def test_async_nested_workflow_session_state(shared_db):
    """Test session state sharing in async nested workflow."""

    async def async_set_state(step_input: StepInput, session_state: dict) -> StepOutput:
        await asyncio.sleep(0.001)
        session_state["async_key"] = "async_value"
        return StepOutput(content="state_set")

    async def async_read_state(step_input: StepInput, session_state: dict) -> StepOutput:
        await asyncio.sleep(0.001)
        val = session_state.get("async_key", "NOT_FOUND")
        return StepOutput(content=f"state_read: {val}")

    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="setter", executor=async_set_state)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="reader", executor=async_read_state),
        ],
    )

    response = await outer.arun(input="test")

    assert "state_read: async_value" in response.step_results[1].content


# ============================================================================
# STORAGE / EXECUTOR RUNS TESTS
# ============================================================================


def test_nested_workflow_stored_in_step_executor_runs(shared_db):
    """Test that nested workflow run is stored in parent's step_executor_runs."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="final", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert response.step_executor_runs is not None
    # Should have at least the nested workflow run
    nested_runs = [r for r in response.step_executor_runs if isinstance(r, WorkflowRunOutput)]
    assert len(nested_runs) == 1
    assert nested_runs[0].workflow_name == "Inner Workflow"
    assert nested_runs[0].parent_run_id == response.run_id


def test_nested_workflow_metrics_aggregated(shared_db):
    """Test that nested workflow metrics are aggregated into StepOutput."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Step(name="step1", executor=step_a),
            Step(name="step2", executor=step_b),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    response = outer.run(input="test")

    nested_output = response.step_results[0]
    # Metrics may or may not be present (function steps don't produce RunMetrics)
    # but the field should exist and not cause serialization errors
    assert nested_output.step_type == StepType.WORKFLOW


# ============================================================================
# SERIALIZATION TESTS
# ============================================================================


def test_nested_workflow_output_serialization(shared_db):
    """Test that nested workflow output can be serialized/deserialized without errors."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    response = outer.run(input="serialize_test")

    # Should not raise
    response_dict = response.to_dict()
    assert response_dict["status"] == "COMPLETED"
    assert len(response_dict["step_results"]) == 1
    assert response_dict["step_results"][0]["step_type"] == StepType.WORKFLOW
    assert response_dict["step_results"][0]["executor_type"] == "workflow"

    # Round-trip deserialization
    restored = WorkflowRunOutput.from_dict(response_dict)
    # After from_dict, status may be a string or enum depending on deserialization
    status_val = restored.status.value if hasattr(restored.status, "value") else restored.status
    assert status_val == "COMPLETED"
    assert len(restored.step_results) == 1


def test_nested_workflow_step_executor_runs_serialization(shared_db):
    """Test that step_executor_runs with nested WorkflowRunOutput serializes correctly."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    response = outer.run(input="test")
    response_dict = response.to_dict()

    # step_executor_runs should have the nested workflow run
    assert "step_executor_runs" in response_dict
    assert len(response_dict["step_executor_runs"]) >= 1

    # The nested run should have workflow_name
    nested_run_dict = response_dict["step_executor_runs"][0]
    assert nested_run_dict.get("workflow_name") == "Inner Workflow"
    assert nested_run_dict.get("parent_run_id") == response.run_id


def test_three_level_serialization_round_trip(shared_db):
    """Test that 3-level nested workflow serializes and deserializes with step_executor_runs intact."""
    level3 = Workflow(
        name="Level 3",
        steps=[Step(name="l3_step", executor=step_a)],
    )

    level2 = Workflow(
        name="Level 2",
        steps=[Step(name="l2_nested", workflow=level3)],
    )

    level1 = Workflow(
        name="Level 1",
        db=shared_db,
        steps=[Step(name="l1_nested", workflow=level2)],
    )

    response = level1.run(input="test")
    response_dict = response.to_dict()

    # Level 1 step_executor_runs should contain Level 2 run
    assert "step_executor_runs" in response_dict
    l2_run = response_dict["step_executor_runs"][0]
    assert l2_run.get("workflow_name") == "Level 2"
    assert l2_run.get("parent_run_id") == response.run_id

    # Level 2 step_executor_runs should contain Level 3 run
    assert "step_executor_runs" in l2_run
    l3_run = l2_run["step_executor_runs"][0]
    assert l3_run.get("workflow_name") == "Level 3"
    assert l3_run.get("parent_run_id") == l2_run["run_id"]

    # Round-trip: deserialize and check structure is preserved
    restored = WorkflowRunOutput.from_dict(response_dict)
    status_val = restored.status.value if hasattr(restored.status, "value") else restored.status
    assert status_val == "COMPLETED"
    assert restored.step_executor_runs is not None
    assert len(restored.step_executor_runs) >= 1

    # The restored Level 2 run should itself have step_executor_runs with Level 3
    l2_restored = restored.step_executor_runs[0]
    assert isinstance(l2_restored, WorkflowRunOutput)
    assert l2_restored.workflow_name == "Level 2"
    assert l2_restored.step_executor_runs is not None
    assert len(l2_restored.step_executor_runs) >= 1


def test_from_dict_depth_guard():
    """Test that from_dict stops recursing at MAX_NESTED_DEPTH to prevent infinite loops."""
    # Build a deeply nested dict structure that exceeds the depth limit
    deepest = {
        "run_id": "deep",
        "workflow_name": "Deep",
        "workflow_id": "deep",
        "parent_run_id": "parent",
        "status": "COMPLETED",
        "content_type": "str",
    }

    # Nest it MAX_NESTED_DEPTH + 1 times
    current = deepest
    for i in range(WorkflowRunOutput._MAX_NESTED_DEPTH + 1):
        current = {
            "run_id": f"level_{i}",
            "workflow_name": f"Level {i}",
            "workflow_id": f"level-{i}",
            "parent_run_id": f"parent_{i}",
            "status": "COMPLETED",
            "content_type": "str",
            "step_executor_runs": [current],
        }

    # Should not raise — depth guard should prevent infinite recursion
    result = WorkflowRunOutput.from_dict(current)
    assert isinstance(result, WorkflowRunOutput)


# ============================================================================
# EDGE CASES
# ============================================================================


def test_nested_workflow_with_no_steps(shared_db):
    """Test nested workflow with empty steps list."""
    inner = Workflow(
        name="Empty Inner",
        steps=[],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after", executor=step_b),
        ],
    )

    # Should complete without crashing
    response = outer.run(input="test")
    assert isinstance(response, WorkflowRunOutput)


def test_workflow_passed_directly_as_step(shared_db):
    """Test passing a Workflow directly in the steps list (auto-wrapping)."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="inner_step", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            inner,  # Passed directly, should be auto-wrapped in Step
            Step(name="final", executor=step_b),
        ],
    )

    response = outer.run(input="auto_wrap_test")

    assert response.status.value == "COMPLETED"
    assert len(response.step_results) == 2
    assert response.step_results[0].executor_type == "workflow"


def test_nested_workflow_shared_session_state(shared_db):
    """Test that session state is shared between outer and nested workflow.

    Function executors access session_state by declaring it as a parameter
    in their function signature. The framework inspects the signature and
    passes the dict automatically.
    """

    def set_state(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["inner_key"] = "inner_value"
        return StepOutput(content="state_set")

    def read_state(step_input: StepInput, session_state: dict) -> StepOutput:
        val = session_state.get("inner_key", "NOT_FOUND")
        return StepOutput(content=f"state_read: {val}")

    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="setter", executor=set_state)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="reader", executor=read_state),
        ],
    )

    response = outer.run(input="test")

    # The outer step should see the state set by the inner workflow
    assert "state_read: inner_value" in response.step_results[1].content


def test_nested_workflow_error_propagation(shared_db):
    """Test that errors in a nested workflow propagate correctly to the parent."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="failing_step", executor=error_step)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner, skip_on_failure=True),
            Step(name="after_error", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # The nested step should have failed but been skipped
    assert response.status.value == "COMPLETED"
    # Should have results from both steps (the failed nested + the follow-up)
    assert len(response.step_results) == 2


def test_nested_workflow_stop_propagation(shared_db):
    """Test that stop=True in a nested workflow step stops the nested workflow."""
    inner = Workflow(
        name="Inner Workflow",
        steps=[
            Step(name="stop_here", executor=stop_step),
            Step(name="should_not_run", executor=step_a),
        ],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="nested", workflow=inner),
            Step(name="after_nested", executor=step_b),
        ],
    )

    response = outer.run(input="test")

    assert isinstance(response, WorkflowRunOutput)
    # The nested workflow should have stopped, but the outer workflow should continue
    nested_output = response.step_results[0]
    assert nested_output.step_type == StepType.WORKFLOW
    assert "Stopped" in (nested_output.content or "")


def test_nested_workflow_receives_previous_step_output(shared_db):
    """Test that a nested workflow as step 2 receives step 1's output (not original input)."""

    def check_input(step_input: StepInput) -> StepOutput:
        """Captures whatever input the nested workflow's step receives."""
        return StepOutput(content=f"received: {step_input.input}")

    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="check", executor=check_input)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[
            Step(name="first", executor=step_a),  # Produces "StepA: hello"
            Step(name="nested", workflow=inner),  # Should receive "StepA: hello"
        ],
    )

    response = outer.run(input="hello")

    nested_output = response.step_results[1]
    # The inner workflow should have received step_a's output, not "hello"
    assert "StepA: hello" in (nested_output.content or ""), (
        f"Nested workflow should receive previous step output, got: {nested_output.content}"
    )


def test_step_validation_rejects_multiple_executors():
    """Test that Step validation rejects having both agent and workflow set."""
    from agno.agent.agent import Agent

    agent = Agent(name="Test")
    inner = Workflow(name="Inner", steps=[])

    with pytest.raises(ValueError, match="can only have one executor type"):
        Step(name="bad_step", agent=agent, workflow=inner)


def test_nested_workflow_max_depth_guard(shared_db):
    """Test that excessively deep nesting is detected and results in a failed step."""
    from agno.workflow.step import _MAX_NESTED_WORKFLOW_DEPTH, _nested_workflow_depth

    # Simulate being at max depth already
    _nested_workflow_depth.set(_MAX_NESTED_WORKFLOW_DEPTH)

    inner = Workflow(
        name="Inner Workflow",
        steps=[Step(name="a", executor=step_a)],
    )

    outer = Workflow(
        name="Outer Workflow",
        db=shared_db,
        steps=[Step(name="nested", workflow=inner)],
    )

    try:
        response = outer.run(input="test")
        # The nested step should have failed due to depth guard
        nested_output = response.step_results[0]
        assert nested_output.success is False
        assert "Maximum nested workflow depth" in (nested_output.error or "")
    finally:
        # Clean up context var state
        _nested_workflow_depth.set(0)
