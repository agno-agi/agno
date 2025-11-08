"""Integration tests for parallel session state handling in workflows."""

import asyncio
from copy import deepcopy

import pytest

from agno.run.base import RunContext, RunStatus
from agno.utils.merge_dict import merge_parallel_session_states
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow


def test_basic_parallel_modifications(shared_db):
    """Test basic parallel modifications to different keys"""

    def func_a(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["a"] += 1
        return StepOutput(content="A done")

    def func_b(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["b"] += 1
        return StepOutput(content="B done")

    def func_c(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["c"] += 1
        return StepOutput(content="C done")

    workflow = Workflow(
        name="Basic Parallel Test",
        steps=[
            Parallel(
                Step(name="Step A", executor=func_a),
                Step(name="Step B", executor=func_b),
                Step(name="Step C", executor=func_c),
            )
        ],
        session_state={"a": 1, "b": 2, "c": 3},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    assert final_state == {"a": 2, "b": 3, "c": 4}


def test_basic_parallel_modifications_with_run_context(shared_db):
    """Test basic parallel modifications to different keys, using the run context"""

    def func_a(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["a"] += 1  # type: ignore
        return StepOutput(content="A done")

    def func_b(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["b"] += 1  # type: ignore
        return StepOutput(content="B done")

    def func_c(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["c"] += 1  # type: ignore
        return StepOutput(content="C done")

    workflow = Workflow(
        name="Basic Parallel Test",
        steps=[
            Parallel(
                Step(name="Step A", executor=func_a),
                Step(name="Step B", executor=func_b),
                Step(name="Step C", executor=func_c),
            )
        ],
        session_state={"a": 1, "b": 2, "c": 3},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    assert final_state == {"a": 2, "b": 3, "c": 4}


def test_overlapping_modifications(shared_db):
    """Test when multiple functions modify the same key"""

    def func_increment_counter(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["counter"] = session_state.get("counter", 0) + 1
        return StepOutput(content="Counter incremented")

    def func_add_to_counter(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["counter"] = session_state.get("counter", 0) + 5
        return StepOutput(content="Added 5 to counter")

    def func_multiply_counter(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["counter"] = session_state.get("counter", 0) + 10
        return StepOutput(content="Counter multiplied")

    workflow = Workflow(
        name="Overlapping Modifications Test",
        steps=[
            Parallel(
                Step(name="Increment", executor=func_increment_counter),
                Step(name="Add 5", executor=func_add_to_counter),
                Step(name="Multiply", executor=func_multiply_counter),
            )
        ],
        session_state={"counter": 10},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    # All operations should be applied (+1, +5, +10)
    expected_result = 26

    assert final_state["counter"] == expected_result


def test_overlapping_modifications_with_run_context(shared_db):
    """Test when multiple functions modify the same key, using the run RunContext"""

    def func_increment_counter(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["counter"] = run_context.session_state.get("counter", 0) + 1  # type: ignore
        return StepOutput(content="Counter incremented")

    def func_add_to_counter(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["counter"] = run_context.session_state.get("counter", 0) + 5  # type: ignore
        return StepOutput(content="Added 5 to counter")

    def func_multiply_counter(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["counter"] = run_context.session_state.get("counter", 0) + 10  # type: ignore
        return StepOutput(content="Counter multiplied")

    workflow = Workflow(
        name="Overlapping Modifications Test",
        steps=[
            Parallel(
                Step(name="Increment", executor=func_increment_counter),
                Step(name="Add 5", executor=func_add_to_counter),
                Step(name="Multiply", executor=func_multiply_counter),
            )
        ],
        session_state={"counter": 10},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    # All operations should be applied (+1, +5, +10)
    expected_result = 26

    assert final_state["counter"] == expected_result


def test_new_key_additions(shared_db):
    """Test adding new keys to session state in parallel"""

    def func_add_x(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["x"] = "added by func_x"
        return StepOutput(content="X added")

    def func_add_y(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["y"] = "added by func_y"
        return StepOutput(content="Y added")

    def func_add_z(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["z"] = "added by func_z"
        return StepOutput(content="Z added")

    workflow = Workflow(
        name="New Key Additions Test",
        steps=[
            Parallel(
                Step(name="Add X", executor=func_add_x),
                Step(name="Add Y", executor=func_add_y),
                Step(name="Add Z", executor=func_add_z),
            )
        ],
        session_state={"initial": "value"},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {"initial": "value", "x": "added by func_x", "y": "added by func_y", "z": "added by func_z"}
    assert final_state == expected


def test_new_key_additions_with_run_context(shared_db):
    """Test adding new keys to session state in parallel, using the run context"""

    def func_add_x(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["x"] = "added by func_x"  # type: ignore
        return StepOutput(content="X added")

    def func_add_y(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["y"] = "added by func_y"  # type: ignore
        return StepOutput(content="Y added")

    def func_add_z(step_input: StepInput, run_context: RunContext) -> StepOutput:
        run_context.session_state["z"] = "added by func_z"  # type: ignore
        return StepOutput(content="Z added")

    workflow = Workflow(
        name="New Key Additions Test",
        steps=[
            Parallel(
                Step(name="Add X", executor=func_add_x),
                Step(name="Add Y", executor=func_add_y),
                Step(name="Add Z", executor=func_add_z),
            )
        ],
        session_state={"initial": "value"},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {"initial": "value", "x": "added by func_x", "y": "added by func_y", "z": "added by func_z"}
    assert final_state == expected


def test_nested_dictionary_modifications(shared_db):
    """Test modifications to nested dictionaries"""

    def func_update_user(step_input: StepInput, session_state: dict) -> StepOutput:
        if "user" not in session_state:
            session_state["user"] = {}
        session_state["user"]["name"] = "Updated by func_user"
        return StepOutput(content="User updated")

    def func_update_config(step_input: StepInput, session_state: dict) -> StepOutput:
        if "config" not in session_state:
            session_state["config"] = {}
        session_state["config"]["debug"] = True
        return StepOutput(content="Config updated")

    def func_update_metrics(step_input: StepInput, session_state: dict) -> StepOutput:
        if "metrics" not in session_state:
            session_state["metrics"] = {}
        session_state["metrics"]["count"] = 100
        return StepOutput(content="Metrics updated")

    workflow = Workflow(
        name="Nested Dictionary Test",
        steps=[
            Parallel(
                Step(name="Update User", executor=func_update_user),
                Step(name="Update Config", executor=func_update_config),
                Step(name="Update Metrics", executor=func_update_metrics),
            )
        ],
        session_state={"initial": "data"},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {
        "initial": "data",
        "user": {"name": "Updated by func_user"},
        "config": {"debug": True},
        "metrics": {"count": 100},
    }
    assert final_state == expected


def test_nested_dictionary_modifications_with_run_context(shared_db):
    """Test modifications to nested dictionaries, using the run context"""

    def func_update_user(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        if "user" not in run_context.session_state:
            run_context.session_state["user"] = {}
        run_context.session_state["user"]["name"] = "Updated by func_user"
        return StepOutput(content="User updated")

    def func_update_config(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        if "config" not in run_context.session_state:
            run_context.session_state["config"] = {}
        run_context.session_state["config"]["debug"] = True
        return StepOutput(content="Config updated")

    def func_update_metrics(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        if "metrics" not in run_context.session_state:
            run_context.session_state["metrics"] = {}
        run_context.session_state["metrics"]["count"] = 100
        return StepOutput(content="Metrics updated")

    workflow = Workflow(
        name="Nested Dictionary Test",
        steps=[
            Parallel(
                Step(name="Update User", executor=func_update_user),
                Step(name="Update Config", executor=func_update_config),
                Step(name="Update Metrics", executor=func_update_metrics),
            )
        ],
        session_state={"initial": "data"},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {
        "initial": "data",
        "user": {"name": "Updated by func_user"},
        "config": {"debug": True},
        "metrics": {"count": 100},
    }
    assert final_state == expected


def test_empty_session_state(shared_db):
    """Test parallel execution with empty session state"""

    def func_a(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["created_by_a"] = "value_a"
        return StepOutput(content="A done")

    def func_b(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["created_by_b"] = "value_b"
        return StepOutput(content="B done")

    workflow = Workflow(
        name="Empty Session State Test",
        steps=[
            Parallel(
                Step(name="Step A", executor=func_a),
                Step(name="Step B", executor=func_b),
            )
        ],
        session_state={},  # Empty session state
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {"created_by_a": "value_a", "created_by_b": "value_b"}
    assert final_state == expected


def test_none_session_state(shared_db):
    """Test parallel execution with None session state"""

    def func_a(step_input: StepInput, session_state: dict) -> StepOutput:
        # This should handle the case where session_state could be None
        if session_state is not None:
            session_state["created_by_a"] = "value_a"
        return StepOutput(content="A done")

    workflow = Workflow(
        name="None Session State Test",
        steps=[
            Parallel(
                Step(name="Step A", executor=func_a),
            )
        ],
        session_state=None,  # None session state
        db=shared_db,
    )

    # This should not crash
    workflow.run("test")
    final_state = workflow.get_session_state()

    # When session_state=None, workflow initializes it as empty dict
    # So the function should be able to add to it
    assert "created_by_a" in final_state
    assert final_state["created_by_a"] == "value_a"


def test_failed_steps_exception_handling(shared_db):
    """Test parallel execution with some steps failing"""

    def func_success(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["success"] = True
        return StepOutput(content="Success")

    def func_failure(step_input: StepInput, session_state: dict) -> StepOutput:
        # This will cause an intentional error
        raise ValueError("Intentional test failure")

    def func_another_success(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["another_success"] = True
        return StepOutput(content="Another Success")

    workflow = Workflow(
        name="Failed Steps Test",
        steps=[
            Parallel(
                Step(name="Success Step", executor=func_success),
                Step(name="Failure Step", executor=func_failure),
                Step(name="Another Success Step", executor=func_another_success),
            )
        ],
        session_state={"initial": "value"},
        db=shared_db,
    )

    # Should not crash even with failures
    result = workflow.run("test")
    final_state = workflow.get_session_state()

    # Successful steps should still have updated session state
    expected = {"initial": "value", "success": True, "another_success": True}
    assert final_state == expected

    # Workflow completes successfully even with some parallel step failures
    # The failed steps are logged but don't fail the overall workflow
    assert result.status == RunStatus.completed


def test_no_modifications(shared_db):
    """Test parallel execution where functions don't modify session state"""

    def func_read_only_a(step_input: StepInput, session_state: dict) -> StepOutput:
        # Only read, don't modify
        value = session_state.get("data", "default")
        return StepOutput(content=f"Read: {value}")

    def func_read_only_b(step_input: StepInput, session_state: dict) -> StepOutput:
        # Only read, don't modify
        value = session_state.get("data", "default")
        return StepOutput(content=f"Also read: {value}")

    initial_state = {"data": "unchanged", "other": "also unchanged"}
    workflow = Workflow(
        name="No Modifications Test",
        steps=[
            Parallel(
                Step(name="Read Only A", executor=func_read_only_a),
                Step(name="Read Only B", executor=func_read_only_b),
            )
        ],
        session_state=deepcopy(initial_state),
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    # Session state should remain unchanged
    assert final_state == initial_state


def test_list_modifications(shared_db):
    """Test modifications to lists in session state"""

    def func_append_to_list_a(step_input: StepInput, session_state: dict) -> StepOutput:
        if "list_a" not in session_state:
            session_state["list_a"] = []
        session_state["list_a"].append("item_from_func_a")
        return StepOutput(content="List A updated")

    def func_append_to_list_b(step_input: StepInput, session_state: dict) -> StepOutput:
        if "list_b" not in session_state:
            session_state["list_b"] = []
        session_state["list_b"].append("item_from_func_b")
        return StepOutput(content="List B updated")

    def func_modify_shared_list(step_input: StepInput, session_state: dict) -> StepOutput:
        if "shared_list" in session_state:
            session_state["shared_list"] = session_state["shared_list"] + ["shared_item"]
        return StepOutput(content="Shared list updated")

    workflow = Workflow(
        name="List Modifications Test",
        steps=[
            Parallel(
                Step(name="Update List A", executor=func_append_to_list_a),
                Step(name="Update List B", executor=func_append_to_list_b),
                Step(name="Update Shared List", executor=func_modify_shared_list),
            )
        ],
        session_state={"shared_list": ["initial_item"]},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    # Each function should have created/updated its respective list
    assert "list_a" in final_state
    assert "item_from_func_a" in final_state["list_a"]
    assert "list_b" in final_state
    assert "item_from_func_b" in final_state["list_b"]
    assert "shared_list" in final_state
    assert "shared_item" in final_state["shared_list"]


def test_list_modifications_with_run_context(shared_db):
    """Test modifications to lists in session state, using the run context"""

    def func_append_to_list_a(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        if "list_a" not in run_context.session_state:
            run_context.session_state["list_a"] = []
        run_context.session_state["list_a"].append("item_from_func_a")
        return StepOutput(content="List A updated")

    def func_append_to_list_b(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        if "list_b" not in run_context.session_state:
            run_context.session_state["list_b"] = []
        run_context.session_state["list_b"].append("item_from_func_b")
        return StepOutput(content="List B updated")

    def func_modify_shared_list(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        if "shared_list" in run_context.session_state:
            run_context.session_state["shared_list"] = run_context.session_state["shared_list"] + ["shared_item"]
        return StepOutput(content="Shared list updated")

    workflow = Workflow(
        name="List Modifications Test",
        steps=[
            Parallel(
                Step(name="Update List A", executor=func_append_to_list_a),
                Step(name="Update List B", executor=func_append_to_list_b),
                Step(name="Update Shared List", executor=func_modify_shared_list),
            )
        ],
        session_state={"shared_list": ["initial_item"]},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    # Each function should have created/updated its respective list
    assert "list_a" in final_state
    assert "item_from_func_a" in final_state["list_a"]
    assert "list_b" in final_state
    assert "item_from_func_b" in final_state["list_b"]
    assert "shared_list" in final_state
    assert "shared_item" in final_state["shared_list"]


def test_mixed_data_types(shared_db):
    """Test modifications with various data types"""

    def func_update_int(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["int_value"] = 42
        return StepOutput(content="Int updated")

    def func_update_float(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["float_value"] = 3.14159
        return StepOutput(content="Float updated")

    def func_update_bool(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["bool_value"] = True
        return StepOutput(content="Bool updated")

    def func_update_none(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["none_value"] = None
        return StepOutput(content="None updated")

    workflow = Workflow(
        name="Mixed Data Types Test",
        steps=[
            Parallel(
                Step(name="Update Int", executor=func_update_int),
                Step(name="Update Float", executor=func_update_float),
                Step(name="Update Bool", executor=func_update_bool),
                Step(name="Update None", executor=func_update_none),
            )
        ],
        session_state={"existing": "data"},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {"existing": "data", "int_value": 42, "float_value": 3.14159, "bool_value": True, "none_value": None}
    assert final_state == expected


def test_mixed_data_types_with_run_context(shared_db):
    """Test modifications with various data types, using the run context"""

    def func_update_int(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        run_context.session_state["int_value"] = 42
        return StepOutput(content="Int updated")

    def func_update_float(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        run_context.session_state["float_value"] = 3.14159
        return StepOutput(content="Float updated")

    def func_update_bool(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        run_context.session_state["bool_value"] = True
        return StepOutput(content="Bool updated")

    def func_update_none(step_input: StepInput, run_context: RunContext) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}

        run_context.session_state["none_value"] = None
        return StepOutput(content="None updated")

    workflow = Workflow(
        name="Mixed Data Types Test",
        steps=[
            Parallel(
                Step(name="Update Int", executor=func_update_int),
                Step(name="Update Float", executor=func_update_float),
                Step(name="Update Bool", executor=func_update_bool),
                Step(name="Update None", executor=func_update_none),
            )
        ],
        session_state={"existing": "data"},
        db=shared_db,
    )

    workflow.run("test")
    final_state = workflow.get_session_state()

    expected = {"existing": "data", "int_value": 42, "float_value": 3.14159, "bool_value": True, "none_value": None}
    assert final_state == expected


@pytest.mark.asyncio
async def test_async_parallel_modifications(shared_db):
    """Test async parallel execution with session state modifications"""

    async def async_func_a(step_input: StepInput, session_state: dict) -> StepOutput:
        # Simulate async work
        await asyncio.sleep(0.01)
        session_state["async_a"] = "completed"
        return StepOutput(content="Async A done")

    async def async_func_b(step_input: StepInput, session_state: dict) -> StepOutput:
        # Simulate async work
        await asyncio.sleep(0.01)
        session_state["async_b"] = "completed"
        return StepOutput(content="Async B done")

    workflow = Workflow(
        name="Async Parallel Test",
        steps=[
            Parallel(
                Step(name="Async Step A", executor=async_func_a),
                Step(name="Async Step B", executor=async_func_b),
            )
        ],
        session_state={"sync_data": "exists"},
        db=shared_db,
    )

    # Test async execution
    await workflow.arun("test")
    final_state = workflow.get_session_state()

    expected = {"sync_data": "exists", "async_a": "completed", "async_b": "completed"}
    assert final_state == expected


def test_streaming_parallel_modifications(shared_db):
    """Test sync parallel execution with streaming and session state modifications"""

    def func_stream_a(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["stream_a"] = "stream_completed"
        return StepOutput(content="Stream A done")

    def func_stream_b(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["stream_b"] = "stream_completed"
        return StepOutput(content="Stream B done")

    def func_stream_c(step_input: StepInput, session_state: dict) -> StepOutput:
        session_state["shared_stream"] = session_state.get("shared_stream", 0) + 1
        return StepOutput(content="Stream C done")

    workflow = Workflow(
        name="Streaming Parallel Test",
        steps=[
            Parallel(
                Step(name="Stream Step A", executor=func_stream_a),
                Step(name="Stream Step B", executor=func_stream_b),
                Step(name="Stream Step C", executor=func_stream_c),
            )
        ],
        session_state={"initial_data": "exists", "shared_stream": 5},
        db=shared_db,
    )

    # Test streaming execution - collect all events
    events = list(workflow.run("test", stream=True))
    final_state = workflow.get_session_state()

    # Verify that session state was properly modified by all parallel steps
    expected = {
        "initial_data": "exists",
        "shared_stream": 6,  # Should be incremented by func_stream_c
        "stream_a": "stream_completed",
        "stream_b": "stream_completed",
    }
    assert final_state == expected

    # Verify that we received streaming events
    assert len(events) > 0


@pytest.mark.asyncio
async def test_async_streaming_parallel_modifications(shared_db):
    """Test async parallel execution with streaming and session state modifications"""

    async def async_func_stream_a(step_input: StepInput, session_state: dict) -> StepOutput:
        # Simulate async work
        await asyncio.sleep(0.01)
        session_state["async_stream_a"] = "async_stream_completed"
        return StepOutput(content="Async Stream A done")

    async def async_func_stream_b(step_input: StepInput, session_state: dict) -> StepOutput:
        # Simulate async work
        await asyncio.sleep(0.01)
        session_state["async_stream_b"] = "async_stream_completed"
        return StepOutput(content="Async Stream B done")

    async def async_func_stream_shared(step_input: StepInput, session_state: dict) -> StepOutput:
        # Simulate async work
        await asyncio.sleep(0.01)
        session_state["shared_async_counter"] = session_state.get("shared_async_counter", 0) + 10
        return StepOutput(content="Async Stream Shared done")

    workflow = Workflow(
        name="Async Streaming Parallel Test",
        steps=[
            Parallel(
                Step(name="Async Stream Step A", executor=async_func_stream_a),
                Step(name="Async Stream Step B", executor=async_func_stream_b),
                Step(name="Async Stream Shared", executor=async_func_stream_shared),
            )
        ],
        session_state={"initial_async_data": "exists", "shared_async_counter": 100},
        db=shared_db,
    )

    # Test async streaming execution - collect all events
    events = []
    async for event in workflow.arun("test", stream=True):
        events.append(event)

    final_state = workflow.get_session_state()

    # Verify that session state was properly modified by all async parallel steps
    expected = {
        "initial_async_data": "exists",
        "shared_async_counter": 110,  # Should be incremented by async_func_stream_shared
        "async_stream_a": "async_stream_completed",
        "async_stream_b": "async_stream_completed",
    }
    assert final_state == expected

    # Verify that we received streaming events
    assert len(events) > 0


def test_streaming_parallel_with_nested_modifications(shared_db):
    """Test streaming parallel execution with nested dictionary modifications"""

    def func_update_config_stream(step_input: StepInput, session_state: dict) -> StepOutput:
        if "config" not in session_state:
            session_state["config"] = {}
        session_state["config"]["streaming"] = True
        return StepOutput(content="Config streaming updated")

    def func_update_stats_stream(step_input: StepInput, session_state: dict) -> StepOutput:
        if "stats" not in session_state:
            session_state["stats"] = {}
        session_state["stats"]["stream_count"] = session_state["stats"].get("stream_count", 0) + 1
        return StepOutput(content="Stats streaming updated")

    workflow = Workflow(
        name="Streaming Nested Parallel Test",
        steps=[
            Parallel(
                Step(name="Config Stream", executor=func_update_config_stream),
                Step(name="Stats Stream", executor=func_update_stats_stream),
            )
        ],
        session_state={"stats": {"existing_count": 5}},
        db=shared_db,
    )

    # Test streaming execution
    events = list(workflow.run("test", stream=True))
    final_state = workflow.get_session_state()

    # Verify nested dictionary modifications
    expected = {"stats": {"existing_count": 5, "stream_count": 1}, "config": {"streaming": True}}
    assert final_state == expected
    assert len(events) > 0


def test_merge_parallel_session_states_directly():
    """Test the merge_parallel_session_states utility function directly"""

    original = {"a": 1, "b": 2, "unchanged": "value"}

    # Simulate what parallel functions would produce
    modified_states = [
        {"a": 10, "b": 2, "unchanged": "value"},  # Changed 'a'
        {"a": 1, "b": 20, "unchanged": "value"},  # Changed 'b'
        {"a": 1, "b": 2, "unchanged": "value", "new_key": "new_value"},  # Added new key
    ]

    merge_parallel_session_states(original, modified_states)

    expected = {"a": 10, "b": 20, "unchanged": "value", "new_key": "new_value"}
    assert original == expected


def test_merge_with_empty_modifications():
    """Test merge function with empty or None modifications"""

    original = {"key": "value"}
    original_copy = deepcopy(original)

    # Test with empty list
    merge_parallel_session_states(original, [])
    assert original == original_copy

    # Test with None values in list
    merge_parallel_session_states(original, [None, None])
    assert original == original_copy

    # Test with empty dicts
    merge_parallel_session_states(original, [{}, {}])
    assert original == original_copy


def test_merge_with_no_changes():
    """Test merge function when modified states have no actual changes"""

    original = {"a": 1, "b": 2, "c": 3}
    original_copy = deepcopy(original)

    # All "modified" states are identical to original
    identical_states = [{"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}]

    merge_parallel_session_states(original, identical_states)

    # Should remain unchanged
    assert original == original_copy
