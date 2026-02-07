"""
Integration tests for Human-In-The-Loop (HITL) workflow functionality.

Tests cover:
- Step confirmation (requires_confirmation) - sync, async, streaming
- Step user input (requires_user_input) - sync, async, streaming
- Router user selection - sync, async, streaming
- Error handling with on_error="pause" - sync, async, streaming
- Step rejection with on_reject="skip" vs on_reject="cancel"
- Workflow pause and resume via continue_run()
- Multiple HITL pauses in a workflow
"""

import pytest

from agno.run.base import RunStatus
from agno.workflow import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


# =============================================================================
# Test Step Functions
# =============================================================================


def fetch_data(step_input: StepInput) -> StepOutput:
    """Simple fetch data function."""
    return StepOutput(content="Fetched data from source")


def process_data(step_input: StepInput) -> StepOutput:
    """Process data function that uses user input if available."""
    user_input = step_input.additional_data.get("user_input", {}) if step_input.additional_data else {}
    preference = user_input.get("preference", "default")
    return StepOutput(content=f"Processed data with preference: {preference}")


def save_data(step_input: StepInput) -> StepOutput:
    """Save data function."""
    prev = step_input.previous_step_content or "no previous content"
    return StepOutput(content=f"Data saved: {prev}")


def failing_step(step_input: StepInput) -> StepOutput:
    """A step that always fails."""
    raise ValueError("Intentional test failure")


def route_a(step_input: StepInput) -> StepOutput:
    """Route A function."""
    return StepOutput(content="Route A executed")


def route_b(step_input: StepInput) -> StepOutput:
    """Route B function."""
    return StepOutput(content="Route B executed")


def route_c(step_input: StepInput) -> StepOutput:
    """Route C function."""
    return StepOutput(content="Route C executed")


# =============================================================================
# Step Confirmation Tests
# =============================================================================


class TestStepConfirmation:
    """Tests for Step confirmation HITL."""

    def test_step_confirmation_pauses_workflow(self, shared_db):
        """Test that a step with requires_confirmation pauses the workflow."""
        workflow = Workflow(
            name="Confirmation Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                    confirmation_message="Proceed with processing?",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        response = workflow.run(input="test data")

        assert response.is_paused is True
        assert response.status == RunStatus.paused
        assert response.step_requirements is not None
        assert len(response.step_requirements) == 1
        assert response.step_requirements[0].step_name == "process"
        assert response.step_requirements[0].confirmation_message == "Proceed with processing?"

    def test_step_confirmation_continue_after_confirm(self, shared_db):
        """Test workflow continues after confirmation."""
        workflow = Workflow(
            name="Confirmation Continue Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = workflow.run(input="test data")
        assert response.is_paused is True

        # Confirm the step
        response.step_requirements[0].confirm()

        # Continue the workflow
        final_response = workflow.continue_run(response)

        assert final_response.status == RunStatus.completed
        assert "Data saved" in final_response.content

    def test_step_confirmation_reject_cancels_workflow(self, shared_db):
        """Test workflow is cancelled when confirmation is rejected (default on_reject=cancel)."""
        workflow = Workflow(
            name="Confirmation Reject Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                    on_reject="cancel",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = workflow.run(input="test data")
        assert response.is_paused is True

        # Reject the step
        response.step_requirements[0].reject()

        # Continue the workflow
        final_response = workflow.continue_run(response)

        assert final_response.status == RunStatus.cancelled

    def test_step_confirmation_reject_skips_step(self, shared_db):
        """Test workflow skips step when rejected with on_reject=skip."""
        workflow = Workflow(
            name="Confirmation Skip Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                    on_reject="skip",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = workflow.run(input="test data")
        assert response.is_paused is True

        # Reject the step
        response.step_requirements[0].reject()

        # Continue the workflow
        final_response = workflow.continue_run(response)

        # Workflow should complete, skipping process step
        assert final_response.status == RunStatus.completed
        # Save step received output from fetch step (not process step since it was skipped)
        assert "Data saved" in final_response.content

    @pytest.mark.asyncio
    async def test_step_confirmation_async(self, async_shared_db):
        """Test step confirmation with async execution."""
        workflow = Workflow(
            name="Async Confirmation Test",
            db=async_shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = await workflow.arun(input="test data")
        assert response.is_paused is True

        # Confirm the step
        response.step_requirements[0].confirm()

        # Continue the workflow
        final_response = await workflow.acontinue_run(response)

        assert final_response.status == RunStatus.completed

    def test_step_confirmation_streaming(self, shared_db):
        """Test step confirmation with streaming execution."""
        from agno.run.workflow import StepPausedEvent, StepStartedEvent, WorkflowStartedEvent

        workflow = Workflow(
            name="Streaming Confirmation Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run with streaming until pause - stream_events=True for step events
        events = list(workflow.run(input="test data", stream=True, stream_events=True))

        # Check we got a workflow started event
        workflow_started = [e for e in events if isinstance(e, WorkflowStartedEvent)]
        assert len(workflow_started) == 1

        # Check we got step started events (fetch should start before we pause on process)
        step_started = [e for e in events if isinstance(e, StepStartedEvent)]
        assert len(step_started) >= 1

        # Check we got a paused event
        paused_events = [e for e in events if isinstance(e, StepPausedEvent)]
        assert len(paused_events) > 0

    def test_step_confirmation_streaming_continue(self, shared_db):
        """Test step confirmation with streaming execution and continue."""
        from agno.run.workflow import StepCompletedEvent, StepStartedEvent

        workflow = Workflow(
            name="Streaming Confirmation Continue Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_confirmation=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run with streaming until pause
        _ = list(workflow.run(input="test data", stream=True, stream_events=True))

        # Get run output from session
        session = workflow.get_session()
        assert session is not None
        response = session.runs[-1]
        assert response.is_paused is True

        # Confirm the step
        response.step_requirements[0].confirm()

        # Continue with streaming - stream_events=True for step events
        continue_events = list(workflow.continue_run(response, stream=True, stream_events=True))

        # Verify we got step events
        step_started = [e for e in continue_events if isinstance(e, StepStartedEvent)]
        step_completed = [e for e in continue_events if isinstance(e, StepCompletedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent"
        assert len(step_completed) >= 1, "Should have at least one StepCompletedEvent"

        # Get final state
        session = workflow.get_session()
        final_response = session.runs[-1]
        assert final_response.status == RunStatus.completed


# =============================================================================
# Step User Input Tests
# =============================================================================


class TestStepUserInput:
    """Tests for Step user input HITL."""

    def test_step_user_input_pauses_workflow(self, shared_db):
        """Test that a step with requires_user_input pauses the workflow."""
        workflow = Workflow(
            name="User Input Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_user_input=True,
                    user_input_message="Please provide your preference",
                    # Step uses List[Dict] for user_input_schema, not List[UserInputField]
                    user_input_schema=[
                        {"name": "preference", "field_type": "str", "description": "Your preference", "required": True},
                    ],
                ),
                Step(name="save", executor=save_data),
            ],
        )

        response = workflow.run(input="test data")

        assert response.is_paused is True
        assert response.step_requirements is not None
        assert len(response.step_requirements) == 1
        assert response.step_requirements[0].requires_user_input is True
        assert response.step_requirements[0].user_input_message == "Please provide your preference"

    def test_step_user_input_continue_with_input(self, shared_db):
        """Test workflow continues with user input."""
        workflow = Workflow(
            name="User Input Continue Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_user_input=True,
                    user_input_message="Please provide your preference",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = workflow.run(input="test data")
        assert response.is_paused is True

        # Provide user input (set_user_input takes **kwargs)
        response.step_requirements[0].set_user_input(preference="fast")

        # Continue the workflow
        final_response = workflow.continue_run(response)

        assert final_response.status == RunStatus.completed
        # The process step should have used the user input
        process_output = [r for r in final_response.step_results if r.step_name == "process"]
        assert len(process_output) == 1
        assert "fast" in process_output[0].content

    @pytest.mark.asyncio
    async def test_step_user_input_async(self, async_shared_db):
        """Test step user input with async execution."""
        workflow = Workflow(
            name="Async User Input Test",
            db=async_shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_user_input=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = await workflow.arun(input="test data")
        assert response.is_paused is True

        # Provide user input (set_user_input takes **kwargs)
        response.step_requirements[0].set_user_input(preference="async_value")

        # Continue the workflow
        final_response = await workflow.acontinue_run(response)

        assert final_response.status == RunStatus.completed

    def test_step_user_input_streaming(self, shared_db):
        """Test step user input with streaming execution."""
        from agno.run.workflow import StepCompletedEvent, StepPausedEvent, StepStartedEvent

        workflow = Workflow(
            name="Streaming User Input Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process",
                    executor=process_data,
                    requires_user_input=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run with streaming until pause - stream_events=True for step events
        events = list(workflow.run(input="test data", stream=True, stream_events=True))

        # Check we got step events before pause
        step_started = [e for e in events if isinstance(e, StepStartedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent"

        # Check we got a paused event with requires_user_input
        paused_events = [e for e in events if isinstance(e, StepPausedEvent)]
        assert len(paused_events) > 0
        assert paused_events[0].requires_user_input is True

        # Get run output from session
        session = workflow.get_session()
        assert session is not None
        response = session.runs[-1]
        assert response.is_paused is True

        # Provide user input
        response.step_requirements[0].set_user_input(preference="streaming_value")

        # Continue with streaming - stream_events=True for step events
        continue_events = list(workflow.continue_run(response, stream=True, stream_events=True))

        # Verify we got step events after continue
        step_started = [e for e in continue_events if isinstance(e, StepStartedEvent)]
        step_completed = [e for e in continue_events if isinstance(e, StepCompletedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent after continue"
        assert len(step_completed) >= 1, "Should have at least one StepCompletedEvent after continue"

        # Get final state
        session = workflow.get_session()
        final_response = session.runs[-1]
        assert final_response.status == RunStatus.completed

        # Verify user input was used
        process_output = [r for r in final_response.step_results if r.step_name == "process"]
        assert len(process_output) == 1
        assert "streaming_value" in process_output[0].content


# =============================================================================
# Router User Selection Tests
# =============================================================================


class TestRouterUserSelection:
    """Tests for Router user selection HITL."""

    def test_router_user_selection_pauses_workflow(self, shared_db):
        """Test that a Router with requires_user_input pauses the workflow."""
        workflow = Workflow(
            name="Router Selection Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Router(
                    name="route_selector",
                    requires_user_input=True,
                    user_input_message="Select a route",
                    choices=[
                        Step(name="route_a", executor=route_a),
                        Step(name="route_b", executor=route_b),
                    ],
                ),
                Step(name="save", executor=save_data),
            ],
        )

        response = workflow.run(input="test data")

        assert response.is_paused is True
        assert response.router_requirements is not None
        assert len(response.router_requirements) == 1
        assert response.router_requirements[0].available_choices == ["route_a", "route_b"]

    def test_router_user_selection_continue(self, shared_db):
        """Test workflow continues after router selection."""
        workflow = Workflow(
            name="Router Selection Continue Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Router(
                    name="route_selector",
                    requires_user_input=True,
                    choices=[
                        Step(name="route_a", executor=route_a),
                        Step(name="route_b", executor=route_b),
                    ],
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = workflow.run(input="test data")
        assert response.is_paused is True

        # Select a route
        response.router_requirements[0].select("route_a")

        # Continue the workflow
        final_response = workflow.continue_run(response)

        assert final_response.status == RunStatus.completed
        # Check route_a was executed
        route_outputs = [r for r in final_response.step_results if r.step_name == "route_selector"]
        assert len(route_outputs) == 1

    def test_router_multi_selection(self, shared_db):
        """Test Router with multiple selections allowed."""
        workflow = Workflow(
            name="Router Multi Selection Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Router(
                    name="route_selector",
                    requires_user_input=True,
                    allow_multiple_selections=True,
                    choices=[
                        Step(name="route_a", executor=route_a),
                        Step(name="route_b", executor=route_b),
                        Step(name="route_c", executor=route_c),
                    ],
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = workflow.run(input="test data")
        assert response.is_paused is True
        assert response.router_requirements[0].allow_multiple_selections is True

        # Select multiple routes
        response.router_requirements[0].select_multiple(["route_a", "route_c"])

        # Continue the workflow
        final_response = workflow.continue_run(response)

        assert final_response.status == RunStatus.completed

    @pytest.mark.asyncio
    async def test_router_user_selection_async(self, async_shared_db):
        """Test Router user selection with async execution."""
        workflow = Workflow(
            name="Async Router Selection Test",
            db=async_shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Router(
                    name="route_selector",
                    requires_user_input=True,
                    choices=[
                        Step(name="route_a", executor=route_a),
                        Step(name="route_b", executor=route_b),
                    ],
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = await workflow.arun(input="test data")
        assert response.is_paused is True

        # Select a route
        response.router_requirements[0].select("route_b")

        # Continue the workflow
        final_response = await workflow.acontinue_run(response)

        assert final_response.status == RunStatus.completed

    def test_router_user_selection_streaming(self, shared_db):
        """Test Router user selection with streaming execution."""
        from agno.run.workflow import RouterPausedEvent, StepCompletedEvent, StepStartedEvent

        workflow = Workflow(
            name="Streaming Router Selection Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Router(
                    name="route_selector",
                    requires_user_input=True,
                    choices=[
                        Step(name="route_a", executor=route_a),
                        Step(name="route_b", executor=route_b),
                    ],
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run with streaming until pause - stream_events=True for step events
        events = list(workflow.run(input="test data", stream=True, stream_events=True))

        # Check we got step events before pause
        step_started = [e for e in events if isinstance(e, StepStartedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent"

        # Check we got a router paused event
        router_paused = [e for e in events if isinstance(e, RouterPausedEvent)]
        assert len(router_paused) > 0
        assert router_paused[0].available_choices == ["route_a", "route_b"]

        # Get run output from session
        session = workflow.get_session()
        assert session is not None
        response = session.runs[-1]
        assert response.is_paused is True
        assert response.router_requirements is not None

        # Select a route
        response.router_requirements[0].select("route_a")

        # Continue with streaming - stream_events=True for step events
        continue_events = list(workflow.continue_run(response, stream=True, stream_events=True))

        # Verify we got step events after continue
        step_started = [e for e in continue_events if isinstance(e, StepStartedEvent)]
        step_completed = [e for e in continue_events if isinstance(e, StepCompletedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent after continue"
        assert len(step_completed) >= 1, "Should have at least one StepCompletedEvent after continue"

        # Get final state
        session = workflow.get_session()
        final_response = session.runs[-1]
        assert final_response.status == RunStatus.completed


# =============================================================================
# Error Handling HITL Tests
# =============================================================================


class TestErrorHandlingHITL:
    """Tests for error handling HITL with on_error='pause'."""

    def test_error_pause_workflow(self, shared_db):
        """Test that a step with on_error='pause' pauses on error."""
        workflow = Workflow(
            name="Error Pause Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="failing",
                    executor=failing_step,
                    on_error="pause",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        response = workflow.run(input="test data")

        assert response.is_paused is True
        assert response.error_requirements is not None
        assert len(response.error_requirements) == 1
        assert response.error_requirements[0].step_name == "failing"
        assert "Intentional test failure" in response.error_requirements[0].error_message

    def test_error_pause_skip(self, shared_db):
        """Test skipping a failed step after pause."""
        workflow = Workflow(
            name="Error Skip Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="failing",
                    executor=failing_step,
                    on_error="pause",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause (due to error)
        response = workflow.run(input="test data")
        assert response.is_paused is True
        assert response.error_requirements is not None

        # Skip the failed step
        response.error_requirements[0].skip()

        # Continue the workflow
        final_response = workflow.continue_run(response)

        assert final_response.status == RunStatus.completed
        # Save step should have executed
        assert "Data saved" in final_response.content

    def test_error_skip_without_pause(self, shared_db):
        """Test on_error='skip' skips step without pausing."""
        workflow = Workflow(
            name="Error Skip Without Pause Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="failing",
                    executor=failing_step,
                    on_error="skip",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        response = workflow.run(input="test data")

        # Workflow should complete without pausing
        assert response.status == RunStatus.completed
        assert "Data saved" in response.content

    def test_error_fail_raises(self, shared_db):
        """Test on_error='fail' raises exception."""
        workflow = Workflow(
            name="Error Fail Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="failing",
                    executor=failing_step,
                    on_error="fail",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        with pytest.raises(ValueError, match="Intentional test failure"):
            workflow.run(input="test data")

    @pytest.mark.asyncio
    async def test_error_pause_async(self, async_shared_db):
        """Test error pause with async execution."""
        workflow = Workflow(
            name="Async Error Pause Test",
            db=async_shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="failing",
                    executor=failing_step,
                    on_error="pause",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run until pause
        response = await workflow.arun(input="test data")
        assert response.is_paused is True
        assert response.error_requirements is not None

        # Skip the failed step
        response.error_requirements[0].skip()

        # Continue the workflow
        final_response = await workflow.acontinue_run(response)

        assert final_response.status == RunStatus.completed

    def test_error_pause_streaming(self, shared_db):
        """Test error pause with streaming execution."""
        from agno.run.workflow import StepCompletedEvent, StepErrorEvent, StepStartedEvent

        workflow = Workflow(
            name="Streaming Error Pause Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="failing",
                    executor=failing_step,
                    on_error="pause",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # Run with streaming until pause - stream_events=True for step events
        events = list(workflow.run(input="test data", stream=True, stream_events=True))

        # Check we got step events before error
        step_started = [e for e in events if isinstance(e, StepStartedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent"

        # Check we got an error event
        error_events = [e for e in events if isinstance(e, StepErrorEvent)]
        assert len(error_events) > 0
        assert error_events[0].step_name == "failing"

        # Get run output from session
        session = workflow.get_session()
        assert session is not None
        response = session.runs[-1]
        assert response.is_paused is True
        assert response.error_requirements is not None

        # Skip the failed step
        response.error_requirements[0].skip()

        # Continue with streaming - stream_events=True for step events
        continue_events = list(workflow.continue_run(response, stream=True, stream_events=True))

        # Verify we got step events after continue
        step_started = [e for e in continue_events if isinstance(e, StepStartedEvent)]
        step_completed = [e for e in continue_events if isinstance(e, StepCompletedEvent)]
        assert len(step_started) >= 1, "Should have at least one StepStartedEvent after continue"
        assert len(step_completed) >= 1, "Should have at least one StepCompletedEvent after continue"

        # Get final state
        session = workflow.get_session()
        final_response = session.runs[-1]
        assert final_response.status == RunStatus.completed
        assert "Data saved" in final_response.content


# =============================================================================
# Multiple HITL Pauses Tests
# =============================================================================


class TestMultipleHITLPauses:
    """Tests for workflows with multiple HITL pauses."""

    def test_multiple_confirmation_steps(self, shared_db):
        """Test workflow with multiple confirmation steps."""
        workflow = Workflow(
            name="Multiple Confirmations Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="process1",
                    executor=process_data,
                    requires_confirmation=True,
                    confirmation_message="Confirm step 1?",
                ),
                Step(
                    name="process2",
                    executor=process_data,
                    requires_confirmation=True,
                    confirmation_message="Confirm step 2?",
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # First run - pauses at process1
        response = workflow.run(input="test data")
        assert response.is_paused is True
        assert response.step_requirements[0].step_name == "process1"

        # Confirm first step
        response.step_requirements[0].confirm()

        # Continue - pauses at process2
        response = workflow.continue_run(response)
        assert response.is_paused is True
        assert response.step_requirements[0].step_name == "process2"

        # Confirm second step
        response.step_requirements[0].confirm()

        # Continue - completes
        final_response = workflow.continue_run(response)
        assert final_response.status == RunStatus.completed

    def test_confirmation_then_user_input(self, shared_db):
        """Test workflow with confirmation followed by user input."""
        workflow = Workflow(
            name="Confirm Then Input Test",
            db=shared_db,
            steps=[
                Step(name="fetch", executor=fetch_data),
                Step(
                    name="confirm_step",
                    executor=process_data,
                    requires_confirmation=True,
                ),
                Step(
                    name="input_step",
                    executor=process_data,
                    requires_user_input=True,
                ),
                Step(name="save", executor=save_data),
            ],
        )

        # First run - pauses at confirmation
        response = workflow.run(input="test data")
        assert response.is_paused is True
        assert response.step_requirements[0].requires_confirmation is True

        # Confirm
        response.step_requirements[0].confirm()

        # Continue - pauses at user input
        response = workflow.continue_run(response)
        assert response.is_paused is True
        assert response.step_requirements[0].requires_user_input is True

        # Provide input (set_user_input takes **kwargs)
        response.step_requirements[0].set_user_input(preference="final")

        # Continue - completes
        final_response = workflow.continue_run(response)
        assert final_response.status == RunStatus.completed
