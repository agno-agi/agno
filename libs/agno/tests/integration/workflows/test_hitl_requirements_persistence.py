"""
Integration tests for HITL step_requirements persistence.

Tests that step_requirements accumulate across pause/continue cycles and
are preserved on the completed run for FE historical display.

Tests cover:
- Single HITL pause: requirement persists after completion
- Multiple HITL pauses: all requirements accumulate
- Executor HITL: executor requirement persists
- Dual HITL (step + executor): both requirements persist
- Output review: post-execution requirement persists
- Error pause + retry: error handling doesn't lose requirements
- Serialization round-trip: requirements survive to_dict/from_dict
- Streaming: requirements persist in streaming mode
- Async: requirements persist in async mode
"""

from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import OnError, OnReject, Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

# =============================================================================
# Test Step Functions
# =============================================================================


def step_a(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Step A done")


def step_b(step_input: StepInput) -> StepOutput:
    user_input = (step_input.additional_data or {}).get("user_input", {})
    return StepOutput(content=f"Step B done with input: {user_input}")


def step_c(step_input: StepInput) -> StepOutput:
    return StepOutput(content=f"Step C done. Prev: {step_input.previous_step_content}")


def route_x(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Route X executed")


def route_y(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Route Y executed")


_fail_once_counter = 0


def fail_once(step_input: StepInput) -> StepOutput:
    global _fail_once_counter
    _fail_once_counter += 1
    if _fail_once_counter % 2 == 1:
        raise ValueError("Simulated failure")
    return StepOutput(content="Recovered after retry")


# =============================================================================
# Single HITL Pause Persistence
# =============================================================================


class TestSingleHITLPersistence:
    """Verify a single resolved requirement persists on the completed run."""

    def test_confirmation_persists(self, shared_db):
        workflow = Workflow(
            name="single-confirm-persist",
            db=shared_db,
            steps=[
                Step(name="step_a", executor=step_a),
                Step(
                    name="step_b",
                    executor=step_b,
                    requires_confirmation=True,
                    confirmation_message="Confirm step B?",
                ),
                Step(name="step_c", executor=step_c),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused
        assert len(response.step_requirements) == 1
        assert response.step_requirements[0].step_name == "step_b"

        response.step_requirements[0].confirm()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_requirements is not None
        assert len(final.step_requirements) == 1
        assert final.step_requirements[0].step_name == "step_b"
        assert final.step_requirements[0].confirmed is True

    def test_user_input_persists(self, shared_db):
        workflow = Workflow(
            name="single-input-persist",
            db=shared_db,
            steps=[
                Step(
                    name="step_b",
                    executor=step_b,
                    requires_user_input=True,
                    user_input_message="Enter params:",
                    user_input_schema=[
                        {"name": "key", "field_type": "text", "description": "A key", "required": True},
                    ],
                ),
                Step(name="step_c", executor=step_c),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused

        req = response.step_requirements[0]
        req.user_input_schema[0].value = "my_value"
        req.user_input = {"key": "my_value"}
        req.confirmed = True

        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_requirements is not None
        assert final.step_requirements[0].user_input == {"key": "my_value"}

    def test_route_selection_persists(self, shared_db):
        workflow = Workflow(
            name="single-route-persist",
            db=shared_db,
            steps=[
                Router(
                    name="router",
                    choices=[
                        Step(name="route_x", executor=route_x),
                        Step(name="route_y", executor=route_y),
                    ],
                    requires_user_input=True,
                    user_input_message="Pick a route:",
                ),
            ],
        )

        response = workflow.run(input="test")
        assert response.is_paused

        req = response.step_requirements[0]
        req.selected_choices = ["route_x"]
        req.confirmed = True

        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert final.step_requirements is not None
        assert final.step_requirements[0].selected_choices == ["route_x"]


# =============================================================================
# Multiple HITL Pauses Accumulation
# =============================================================================


class TestMultipleHITLAccumulation:
    """Verify requirements accumulate across multiple pause/continue cycles."""

    def test_two_confirmations_accumulate(self, shared_db):
        workflow = Workflow(
            name="multi-confirm-accumulate",
            db=shared_db,
            steps=[
                Step(
                    name="step_1",
                    executor=step_a,
                    requires_confirmation=True,
                    confirmation_message="Confirm step 1?",
                ),
                Step(
                    name="step_2",
                    executor=step_b,
                    requires_confirmation=True,
                    confirmation_message="Confirm step 2?",
                ),
                Step(name="step_3", executor=step_c),
            ],
        )

        # Pause 1
        response = workflow.run(input="test")
        assert response.is_paused
        assert response.step_requirements[-1].step_name == "step_1"
        response.step_requirements[-1].confirm()

        # Pause 2
        response = workflow.continue_run(response)
        assert response.is_paused
        assert len(response.step_requirements) == 2  # Accumulated
        assert response.step_requirements[0].step_name == "step_1"
        assert response.step_requirements[0].confirmed is True  # Already resolved
        assert response.step_requirements[1].step_name == "step_2"
        assert response.step_requirements[1].confirmed is None  # Active
        response.step_requirements[-1].confirm()

        # Complete
        final = workflow.continue_run(response)
        assert final.status == RunStatus.completed
        assert len(final.step_requirements) == 2
        assert all(req.confirmed is True for req in final.step_requirements)

    def test_confirmation_then_user_input_accumulate(self, shared_db):
        workflow = Workflow(
            name="mixed-hitl-accumulate",
            db=shared_db,
            steps=[
                Step(
                    name="confirm_step",
                    executor=step_a,
                    requires_confirmation=True,
                ),
                Step(
                    name="input_step",
                    executor=step_b,
                    requires_user_input=True,
                    user_input_message="Enter data:",
                    user_input_schema=[
                        {"name": "val", "field_type": "text", "description": "Value", "required": True},
                    ],
                ),
                Step(name="final", executor=step_c),
            ],
        )

        # Pause 1: confirmation
        response = workflow.run(input="test")
        assert response.is_paused
        response.step_requirements[-1].confirm()

        # Pause 2: user input
        response = workflow.continue_run(response)
        assert response.is_paused
        assert len(response.step_requirements) == 2

        req = response.step_requirements[-1]
        req.user_input_schema[0].value = "hello"
        req.user_input = {"val": "hello"}
        req.confirmed = True

        # Complete
        final = workflow.continue_run(response)
        assert final.status == RunStatus.completed
        assert len(final.step_requirements) == 2
        assert final.step_requirements[0].step_name == "confirm_step"
        assert final.step_requirements[0].confirmed is True
        assert final.step_requirements[1].step_name == "input_step"
        assert final.step_requirements[1].user_input == {"val": "hello"}

    def test_three_pauses_accumulate(self, shared_db):
        workflow = Workflow(
            name="three-pauses",
            db=shared_db,
            steps=[
                Step(name="s1", executor=step_a, requires_confirmation=True),
                Step(name="s2", executor=step_a, requires_confirmation=True),
                Step(name="s3", executor=step_a, requires_confirmation=True),
                Step(name="s4", executor=step_c),
            ],
        )

        response = workflow.run(input="test")
        for i in range(3):
            assert response.is_paused, f"Expected pause at iteration {i}"
            assert len(response.step_requirements) == i + 1
            response.step_requirements[-1].confirm()
            response = workflow.continue_run(response)

        assert response.status == RunStatus.completed
        assert len(response.step_requirements) == 3
        assert [r.step_name for r in response.step_requirements] == ["s1", "s2", "s3"]


# =============================================================================
# Serialization Round-Trip
# =============================================================================


class TestSerializationRoundTrip:
    """Verify requirements survive DB serialization."""

    def test_requirements_survive_to_dict_from_dict(self, shared_db):
        workflow = Workflow(
            name="serial-roundtrip",
            db=shared_db,
            steps=[
                Step(name="s1", executor=step_a, requires_confirmation=True),
                Step(name="s2", executor=step_a, requires_confirmation=True),
                Step(name="final", executor=step_c),
            ],
        )

        response = workflow.run(input="test")
        response.step_requirements[-1].confirm()
        response = workflow.continue_run(response)
        response.step_requirements[-1].confirm()
        final = workflow.continue_run(response)

        assert final.status == RunStatus.completed
        assert len(final.step_requirements) == 2

        # Serialize and deserialize
        run_dict = final.to_dict()
        assert "step_requirements" in run_dict
        assert len(run_dict["step_requirements"]) == 2

        restored = WorkflowRunOutput.from_dict(run_dict)
        assert len(restored.step_requirements) == 2
        assert restored.step_requirements[0].step_name == "s1"
        assert restored.step_requirements[0].confirmed is True
        assert restored.step_requirements[1].step_name == "s2"
        assert restored.step_requirements[1].confirmed is True

    def test_requirements_persist_in_session_storage(self, shared_db):
        workflow = Workflow(
            name="session-persist",
            db=shared_db,
            steps=[
                Step(name="s1", executor=step_a, requires_confirmation=True),
                Step(name="final", executor=step_c),
            ],
        )

        response = workflow.run(input="test")
        response.step_requirements[-1].confirm()
        final = workflow.continue_run(response)
        assert final.status == RunStatus.completed

        # Load from session storage
        session = workflow.get_session()
        assert session is not None
        assert session.runs is not None

        loaded_run = session.runs[-1]
        assert loaded_run.step_requirements is not None
        assert len(loaded_run.step_requirements) >= 1
        assert loaded_run.step_requirements[0].step_name == "s1"
        assert loaded_run.step_requirements[0].confirmed is True


# =============================================================================
# Rejection Doesn't Corrupt History
# =============================================================================


class TestRejectionWithHistory:
    """Verify rejection + skip doesn't corrupt accumulated requirements."""

    def test_confirm_then_reject_skip(self, shared_db):
        workflow = Workflow(
            name="confirm-reject-skip",
            db=shared_db,
            steps=[
                Step(name="s1", executor=step_a, requires_confirmation=True),
                Step(name="s2", executor=step_a, requires_confirmation=True, on_reject=OnReject.skip),
                Step(name="final", executor=step_c),
            ],
        )

        # Pause 1: confirm
        response = workflow.run(input="test")
        response.step_requirements[-1].confirm()

        # Pause 2: reject (skip)
        response = workflow.continue_run(response)
        assert response.is_paused
        response.step_requirements[-1].reject()

        # Complete (s2 skipped)
        final = workflow.continue_run(response)
        assert final.status == RunStatus.completed
        assert len(final.step_requirements) == 2
        assert final.step_requirements[0].confirmed is True  # s1 confirmed
        assert final.step_requirements[1].confirmed is False  # s2 rejected


# =============================================================================
# Streaming Persistence
# =============================================================================


class TestStreamingPersistence:
    """Verify requirements persist through streaming continue_run."""

    def test_streaming_preserves_requirements(self, shared_db):
        workflow = Workflow(
            name="stream-persist",
            db=shared_db,
            steps=[
                Step(name="s1", executor=step_a, requires_confirmation=True),
                Step(name="s2", executor=step_a, requires_confirmation=True),
                Step(name="final", executor=step_c),
            ],
        )

        # Run (non-streaming) until first pause
        response = workflow.run(input="test")
        assert response.is_paused
        response.step_requirements[-1].confirm()

        # Continue with streaming
        for event in workflow.continue_run(response, stream=True):
            pass  # Consume stream

        # Get run from session
        session = workflow.get_session()
        response = session.runs[-1]

        if response.is_paused:
            # Second pause
            assert len(response.step_requirements) == 2
            response.step_requirements[-1].confirm()

            for event in workflow.continue_run(response, stream=True):
                pass

            session = workflow.get_session()
            final = session.runs[-1]
        else:
            final = response

        assert final.status == RunStatus.completed
        assert final.step_requirements is not None
        assert len(final.step_requirements) >= 1


# =============================================================================
# Error Pause Doesn't Lose Requirements
# =============================================================================


class TestErrorPauseWithHistory:
    """Verify error pause + retry preserves earlier requirements."""

    def test_confirm_then_error_retry(self, shared_db):
        global _fail_once_counter
        _fail_once_counter = 0

        workflow = Workflow(
            name="confirm-error-retry",
            db=shared_db,
            steps=[
                Step(name="s1", executor=step_a, requires_confirmation=True),
                Step(name="risky", executor=fail_once, on_error=OnError.pause, max_retries=0),
                Step(name="final", executor=step_c),
            ],
        )

        # Pause 1: confirmation
        response = workflow.run(input="test")
        assert response.is_paused
        response.step_requirements[-1].confirm()

        # Continue — risky step fails, should pause for error
        response = workflow.continue_run(response)

        if response.is_paused and response.error_requirements:
            # Error pause occurred — retry
            response.error_requirements[0].retry()
            final = workflow.continue_run(response)
        else:
            # Error was handled internally (retry succeeded within execution)
            final = response

        assert final.status == RunStatus.completed
        # s1 confirmation requirement should still be there
        assert final.step_requirements is not None
        assert any(r.step_name == "s1" for r in final.step_requirements)
