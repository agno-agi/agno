"""
Unit tests for Human-In-The-Loop (HITL) workflow functionality.

Tests cover:
- Step confirmation (requires_confirmation)
- Step user input (requires_user_input)
- Router user selection (Router.requires_user_input)
- Error handling with on_error="pause"
- Step rejection with on_reject="skip"
- Workflow pause and resume via continue_run()
- StepRequirement (including route selection), ErrorRequirement dataclasses
- Serialization/deserialization of HITL requirements
"""

from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow.step import Step
from agno.workflow.types import (
    ErrorRequirement,
    StepInput,
    StepOutput,
    StepRequirement,
    UserInputField,
)

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
    return StepOutput(content="Data saved successfully")


def failing_step(step_input: StepInput) -> StepOutput:
    """A step that always fails."""
    raise ValueError("Intentional test failure")


# =============================================================================
# StepRequirement Tests
# =============================================================================


class TestStepRequirement:
    """Tests for StepRequirement dataclass."""

    def test_step_requirement_creation(self):
        """Test creating a StepRequirement."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
            confirmation_message="Please confirm this step",
        )

        assert req.step_id == "step-1"
        assert req.step_name == "test_step"
        assert req.step_index == 0
        assert req.requires_confirmation is True
        assert req.confirmation_message == "Please confirm this step"
        assert req.confirmed is None
        assert req.on_reject == "cancel"

    def test_step_requirement_confirm(self):
        """Test confirming a step requirement."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
        )

        assert req.confirmed is None
        req.confirm()
        assert req.confirmed is True

    def test_step_requirement_reject(self):
        """Test rejecting a step requirement."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
        )

        assert req.confirmed is None
        req.reject()
        assert req.confirmed is False

    def test_step_requirement_on_reject_skip(self):
        """Test step requirement with on_reject=skip."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
            on_reject="skip",
        )

        assert req.on_reject == "skip"

    def test_step_requirement_user_input(self):
        """Test step requirement with user input."""
        schema = [
            UserInputField(name="preference", field_type="str", description="Your preference", required=True),
        ]
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_user_input=True,
            user_input_message="Please provide your preference",
            user_input_schema=schema,
        )

        assert req.requires_user_input is True
        assert req.user_input_message == "Please provide your preference"
        assert len(req.user_input_schema) == 1

    def test_step_requirement_set_user_input(self):
        """Test setting user input on a requirement."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_user_input=True,
        )

        # set_user_input takes **kwargs, not a dict
        req.set_user_input(preference="fast")
        assert req.user_input == {"preference": "fast"}

    def test_step_requirement_to_dict(self):
        """Test serializing StepRequirement to dict."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
            confirmation_message="Confirm?",
            on_reject="skip",
        )
        req.confirm()

        data = req.to_dict()

        assert data["step_id"] == "step-1"
        assert data["step_name"] == "test_step"
        assert data["step_index"] == 0
        assert data["requires_confirmation"] is True
        assert data["confirmation_message"] == "Confirm?"
        assert data["confirmed"] is True
        assert data["on_reject"] == "skip"

    def test_step_requirement_from_dict(self):
        """Test deserializing StepRequirement from dict."""
        data = {
            "step_id": "step-1",
            "step_name": "test_step",
            "step_index": 0,
            "requires_confirmation": True,
            "confirmation_message": "Confirm?",
            "confirmed": True,
            "on_reject": "skip",
        }

        req = StepRequirement.from_dict(data)

        assert req.step_id == "step-1"
        assert req.step_name == "test_step"
        assert req.confirmed is True
        assert req.on_reject == "skip"

    def test_step_requirement_roundtrip(self):
        """Test roundtrip serialization of StepRequirement."""
        original = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
            confirmation_message="Confirm?",
            requires_user_input=True,
            user_input_message="Enter preference",
            on_reject="skip",
        )
        original.confirm()
        # set_user_input takes **kwargs
        original.set_user_input(preference="fast")

        data = original.to_dict()
        restored = StepRequirement.from_dict(data)

        assert restored.step_id == original.step_id
        assert restored.step_name == original.step_name
        assert restored.confirmed == original.confirmed
        assert restored.user_input == original.user_input
        assert restored.on_reject == original.on_reject


# =============================================================================
# StepRequirement Route Selection Tests (formerly RouterRequirement)
# =============================================================================


class TestStepRequirementRouteSelection:
    """Tests for StepRequirement with route selection fields."""

    def test_route_selection_requirement_creation(self):
        """Test creating a StepRequirement for route selection."""
        req = StepRequirement(
            step_id="router-1",
            step_name="test_router",
            step_type="Router",
            requires_route_selection=True,
            available_choices=["option_a", "option_b", "option_c"],
            user_input_message="Select a route",
        )

        assert req.step_id == "router-1"
        assert req.step_name == "test_router"
        assert req.requires_route_selection is True
        assert req.available_choices == ["option_a", "option_b", "option_c"]
        assert req.selected_choices is None
        assert req.allow_multiple_selections is False

    def test_route_selection_select_single(self):
        """Test selecting a single route."""
        req = StepRequirement(
            step_id="router-1",
            step_name="test_router",
            step_type="Router",
            requires_route_selection=True,
            available_choices=["option_a", "option_b"],
        )

        req.select("option_a")
        assert req.selected_choices == ["option_a"]

    def test_route_selection_select_multiple(self):
        """Test selecting multiple routes."""
        req = StepRequirement(
            step_id="router-1",
            step_name="test_router",
            step_type="Router",
            requires_route_selection=True,
            available_choices=["option_a", "option_b", "option_c"],
            allow_multiple_selections=True,
        )

        req.select_multiple(["option_a", "option_c"])
        assert req.selected_choices == ["option_a", "option_c"]

    def test_route_selection_to_dict(self):
        """Test serializing route selection StepRequirement to dict."""
        req = StepRequirement(
            step_id="router-1",
            step_name="test_router",
            step_type="Router",
            requires_route_selection=True,
            available_choices=["option_a", "option_b"],
            allow_multiple_selections=True,
        )
        req.select_multiple(["option_a", "option_b"])

        data = req.to_dict()

        assert data["step_id"] == "router-1"
        assert data["step_name"] == "test_router"
        assert data["available_choices"] == ["option_a", "option_b"]
        assert data["selected_choices"] == ["option_a", "option_b"]
        assert data["allow_multiple_selections"] is True

    def test_route_selection_from_dict(self):
        """Test deserializing route selection StepRequirement from dict."""
        data = {
            "step_id": "router-1",
            "step_name": "test_router",
            "step_type": "Router",
            "requires_route_selection": True,
            "available_choices": ["option_a", "option_b"],
            "selected_choices": ["option_a"],
            "allow_multiple_selections": False,
        }

        req = StepRequirement.from_dict(data)

        assert req.step_id == "router-1"
        assert req.requires_route_selection is True
        assert req.selected_choices == ["option_a"]


# =============================================================================
# ErrorRequirement Tests
# =============================================================================


class TestErrorRequirement:
    """Tests for ErrorRequirement dataclass."""

    def test_error_requirement_creation(self):
        """Test creating an ErrorRequirement."""
        req = ErrorRequirement(
            step_id="step-1",
            step_name="failing_step",
            step_index=0,
            error_message="Something went wrong",
            error_type="ValueError",
        )

        assert req.step_id == "step-1"
        assert req.step_name == "failing_step"
        assert req.error_message == "Something went wrong"
        assert req.error_type == "ValueError"
        assert req.retry_count == 0
        assert req.decision is None

    def test_error_requirement_retry(self):
        """Test setting retry decision."""
        req = ErrorRequirement(
            step_id="step-1",
            step_name="failing_step",
            step_index=0,
            error_message="Error",
        )

        assert req.needs_decision is True
        req.retry()
        assert req.decision == "retry"
        assert req.should_retry is True
        assert req.is_resolved is True

    def test_error_requirement_skip(self):
        """Test setting skip decision."""
        req = ErrorRequirement(
            step_id="step-1",
            step_name="failing_step",
            step_index=0,
            error_message="Error",
        )

        req.skip()
        assert req.decision == "skip"
        assert req.should_skip is True
        assert req.is_resolved is True

    def test_error_requirement_to_dict(self):
        """Test serializing ErrorRequirement to dict."""
        req = ErrorRequirement(
            step_id="step-1",
            step_name="failing_step",
            step_index=0,
            error_message="Test error",
            error_type="ValueError",
            retry_count=1,
        )
        req.retry()

        data = req.to_dict()

        assert data["step_id"] == "step-1"
        assert data["step_name"] == "failing_step"
        assert data["error_message"] == "Test error"
        assert data["error_type"] == "ValueError"
        assert data["retry_count"] == 1
        assert data["decision"] == "retry"

    def test_error_requirement_from_dict(self):
        """Test deserializing ErrorRequirement from dict."""
        data = {
            "step_id": "step-1",
            "step_name": "failing_step",
            "step_index": 0,
            "error_message": "Test error",
            "error_type": "ValueError",
            "retry_count": 2,
            "decision": "skip",
        }

        req = ErrorRequirement.from_dict(data)

        assert req.step_id == "step-1"
        assert req.error_message == "Test error"
        assert req.retry_count == 2
        assert req.should_skip is True


# =============================================================================
# Step HITL Configuration Tests
# =============================================================================


class TestStepHITLConfiguration:
    """Tests for Step class HITL configuration."""

    def test_step_requires_confirmation(self):
        """Test Step with requires_confirmation."""
        step = Step(
            name="confirm_step",
            executor=fetch_data,
            requires_confirmation=True,
            confirmation_message="Please confirm this step",
        )

        assert step.requires_confirmation is True
        assert step.confirmation_message == "Please confirm this step"

    def test_step_requires_user_input(self):
        """Test Step with requires_user_input."""
        # Step uses List[Dict] for user_input_schema, not List[UserInputField]
        step = Step(
            name="input_step",
            executor=process_data,
            requires_user_input=True,
            user_input_message="Please provide your preference",
            user_input_schema=[
                {"name": "preference", "field_type": "str", "description": "Your preference", "required": True},
            ],
        )

        assert step.requires_user_input is True
        assert step.user_input_message == "Please provide your preference"
        assert len(step.user_input_schema) == 1

    def test_step_on_reject_cancel(self):
        """Test Step with on_reject=cancel (default)."""
        step = Step(
            name="cancel_step",
            executor=fetch_data,
            requires_confirmation=True,
            on_reject="cancel",
        )

        assert step.on_reject == "cancel"

    def test_step_on_reject_skip(self):
        """Test Step with on_reject=skip."""
        step = Step(
            name="skip_step",
            executor=fetch_data,
            requires_confirmation=True,
            on_reject="skip",
        )

        assert step.on_reject == "skip"

    def test_step_on_error_fail(self):
        """Test Step with on_error=fail (default)."""
        step = Step(
            name="fail_step",
            executor=failing_step,
            on_error="fail",
        )

        assert step.on_error == "fail"

    def test_step_on_error_skip(self):
        """Test Step with on_error=skip."""
        step = Step(
            name="skip_error_step",
            executor=failing_step,
            on_error="skip",
        )

        assert step.on_error == "skip"

    def test_step_on_error_pause(self):
        """Test Step with on_error=pause."""
        step = Step(
            name="pause_error_step",
            executor=failing_step,
            on_error="pause",
        )

        assert step.on_error == "pause"

    def test_step_hitl_to_dict(self):
        """Test serializing Step with HITL config to dict."""
        step = Step(
            name="hitl_step",
            executor=fetch_data,
            requires_confirmation=True,
            confirmation_message="Confirm?",
            requires_user_input=True,
            user_input_message="Input?",
            on_reject="skip",
            on_error="pause",
        )

        data = step.to_dict()

        assert data["requires_confirmation"] is True
        assert data["confirmation_message"] == "Confirm?"
        assert data["requires_user_input"] is True
        assert data["user_input_message"] == "Input?"
        assert data["on_reject"] == "skip"
        assert data["on_error"] == "pause"


# =============================================================================
# WorkflowRunOutput HITL Properties Tests
# =============================================================================


class TestWorkflowRunOutputHITL:
    """Tests for WorkflowRunOutput HITL-related properties."""

    def test_workflow_output_is_paused(self):
        """Test is_paused property."""
        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
        )

        assert output.is_paused is True

    def test_workflow_output_step_requirements(self):
        """Test step_requirements handling."""
        req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
        )

        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            step_requirements=[req],
        )

        assert len(output.step_requirements) == 1
        assert output.step_requirements[0].step_id == "step-1"

    def test_workflow_output_router_requirements(self):
        """Test router_requirements handling (now via step_requirements with requires_route_selection)."""
        req = StepRequirement(
            step_id="router-1",
            step_name="test_router",
            step_type="Router",
            requires_route_selection=True,
            available_choices=["a", "b"],
        )

        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            step_requirements=[req],
        )

        assert len(output.step_requirements) == 1
        assert output.step_requirements[0].step_id == "router-1"

    def test_workflow_output_error_requirements(self):
        """Test error_requirements handling."""
        req = ErrorRequirement(
            step_id="step-1",
            step_name="failing_step",
            step_index=0,
            error_message="Error occurred",
        )

        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            error_requirements=[req],
        )

        assert len(output.error_requirements) == 1
        assert output.error_requirements[0].step_id == "step-1"

    def test_workflow_output_active_step_requirements(self):
        """Test active_step_requirements property."""
        confirmed_req = StepRequirement(
            step_id="step-1",
            step_name="confirmed_step",
            step_index=0,
            requires_confirmation=True,
        )
        confirmed_req.confirm()

        pending_req = StepRequirement(
            step_id="step-2",
            step_name="pending_step",
            step_index=1,
            requires_confirmation=True,
        )

        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            step_requirements=[confirmed_req, pending_req],
        )

        active = output.active_step_requirements
        assert len(active) == 1
        assert active[0].step_id == "step-2"

    def test_workflow_output_to_dict_with_requirements(self):
        """Test serializing WorkflowRunOutput with HITL requirements."""
        step_req = StepRequirement(
            step_id="step-1",
            step_name="test_step",
            step_index=0,
            requires_confirmation=True,
        )

        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            step_requirements=[step_req],
        )

        data = output.to_dict()

        # Status is serialized as the enum value string
        assert data["status"] == RunStatus.paused.value
        assert "step_requirements" in data
        assert len(data["step_requirements"]) == 1

    def test_workflow_output_from_dict_with_requirements(self):
        """Test deserializing WorkflowRunOutput with HITL requirements."""
        data = {
            "run_id": "run-1",
            "session_id": "session-1",
            "workflow_name": "test_workflow",
            "status": RunStatus.paused.value,  # Use enum value
            "step_requirements": [
                {
                    "step_id": "step-1",
                    "step_name": "test_step",
                    "step_index": 0,
                    "requires_confirmation": True,
                    "confirmed": None,
                    "on_reject": "cancel",
                }
            ],
        }

        output = WorkflowRunOutput.from_dict(data)

        # Status may be string or enum after deserialization
        assert str(output.status) == RunStatus.paused.value or output.status == RunStatus.paused
        assert len(output.step_requirements) == 1
        assert output.step_requirements[0].step_id == "step-1"

    def test_workflow_output_paused_step_info(self):
        """Test paused_step_index and paused_step_name fields."""
        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            paused_step_index=2,
            paused_step_name="process_data",
        )

        assert output.paused_step_index == 2
        assert output.paused_step_name == "process_data"

    def test_workflow_output_paused_step_info_serialization(self):
        """Test serialization of paused_step_index and paused_step_name."""
        output = WorkflowRunOutput(
            run_id="run-1",
            session_id="session-1",
            workflow_name="test_workflow",
            status=RunStatus.paused,
            paused_step_index=1,
            paused_step_name="confirm_step",
        )

        data = output.to_dict()

        assert data["paused_step_index"] == 1
        assert data["paused_step_name"] == "confirm_step"

    def test_workflow_output_paused_step_info_deserialization(self):
        """Test deserialization of paused_step_index and paused_step_name."""
        data = {
            "run_id": "run-1",
            "session_id": "session-1",
            "workflow_name": "test_workflow",
            "status": RunStatus.paused.value,
            "paused_step_index": 3,
            "paused_step_name": "final_step",
        }

        output = WorkflowRunOutput.from_dict(data)

        assert output.paused_step_index == 3
        assert output.paused_step_name == "final_step"


# =============================================================================
# UserInputField Tests
# =============================================================================


class TestUserInputField:
    """Tests for UserInputField dataclass."""

    def test_user_input_field_creation(self):
        """Test creating a UserInputField."""
        field = UserInputField(
            name="preference",
            field_type="str",
            description="Your preference",
            required=True,
        )

        assert field.name == "preference"
        assert field.description == "Your preference"
        assert field.field_type == "str"
        assert field.required is True

    def test_user_input_field_defaults(self):
        """Test UserInputField default values."""
        field = UserInputField(
            name="optional_field",
            field_type="str",
            description="Optional field",
            required=False,
        )

        assert field.field_type == "str"
        assert field.required is False
        assert field.value is None

    def test_user_input_field_to_dict(self):
        """Test serializing UserInputField to dict."""
        field = UserInputField(
            name="preference",
            field_type="str",
            description="Your preference",
            required=True,
        )

        data = field.to_dict()

        assert data["name"] == "preference"
        assert data["description"] == "Your preference"
        assert data["field_type"] == "str"
        assert data["required"] is True

    def test_user_input_field_from_dict(self):
        """Test deserializing UserInputField from dict."""
        data = {
            "name": "preference",
            "description": "Your preference",
            "field_type": "str",
            "required": True,
            "value": "fast",
        }

        field = UserInputField.from_dict(data)

        assert field.name == "preference"
        assert field.description == "Your preference"
        assert field.required is True
        assert field.value == "fast"


# =============================================================================
# Condition on_reject Tests
# =============================================================================


class TestConditionOnReject:
    """Tests for Condition on_reject behavior (else, skip, cancel)."""

    def test_condition_on_reject_else_default(self):
        """Test that Condition defaults to on_reject='else'."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            else_steps=[Step(name="else_step", executor=save_data)],
            requires_confirmation=True,
        )

        assert condition.on_reject == OnReject.else_branch

    def test_condition_on_reject_skip(self):
        """Test Condition with on_reject='skip'."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            else_steps=[Step(name="else_step", executor=save_data)],
            requires_confirmation=True,
            on_reject=OnReject.skip,
        )

        assert condition.on_reject == OnReject.skip

    def test_condition_on_reject_cancel(self):
        """Test Condition with on_reject='cancel'."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            requires_confirmation=True,
            on_reject=OnReject.cancel,
        )

        assert condition.on_reject == OnReject.cancel

    def test_condition_create_step_requirement_on_reject_else(self):
        """Test that create_step_requirement includes on_reject='else'."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            else_steps=[Step(name="else_step", executor=save_data)],
            requires_confirmation=True,
            on_reject=OnReject.else_branch,
        )

        step_input = StepInput(input="test")
        req = condition.create_step_requirement(0, step_input)

        assert req.step_type == "Condition"
        assert req.on_reject == "else"
        assert req.requires_confirmation is True

    def test_condition_create_step_requirement_on_reject_skip(self):
        """Test that create_step_requirement includes on_reject='skip'."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            requires_confirmation=True,
            on_reject=OnReject.skip,
        )

        step_input = StepInput(input="test")
        req = condition.create_step_requirement(0, step_input)

        assert req.step_type == "Condition"
        assert req.on_reject == "skip"

    def test_condition_create_step_requirement_on_reject_cancel(self):
        """Test that create_step_requirement includes on_reject='cancel'."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            requires_confirmation=True,
            on_reject=OnReject.cancel,
        )

        step_input = StepInput(input="test")
        req = condition.create_step_requirement(0, step_input)

        assert req.step_type == "Condition"
        assert req.on_reject == "cancel"

    def test_condition_evaluator_defaults_to_true(self):
        """Test that Condition evaluator defaults to True."""
        from agno.workflow.condition import Condition

        # Should not need to specify evaluator when using requires_confirmation
        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            requires_confirmation=True,
        )

        assert condition.evaluator is True

    def test_condition_force_else_branch_with_else_steps(self):
        """Test Condition.execute with force_else_branch=True when else_steps exist."""
        from agno.workflow.condition import Condition

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def else_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="ELSE branch executed")

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=if_step_func)],
            else_steps=[Step(name="else_step", executor=else_step_func)],
        )

        step_input = StepInput(input="test")
        result = condition.execute(step_input, force_else_branch=True)

        # Should execute else branch
        assert "else branch" in result.content.lower()
        assert result.success is True

    def test_condition_force_else_branch_without_else_steps(self):
        """Test Condition.execute with force_else_branch=True when no else_steps."""
        from agno.workflow.condition import Condition

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=if_step_func)],
            # No else_steps
        )

        step_input = StepInput(input="test")
        result = condition.execute(step_input, force_else_branch=True)

        # Should skip since no else_steps
        assert "skipped" in result.content.lower() or "no else branch" in result.content.lower()
        assert result.success is True

    def test_condition_normal_execution_if_branch(self):
        """Test Condition normal execution takes if branch when evaluator is True."""
        from agno.workflow.condition import Condition

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def else_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="ELSE branch executed")

        condition = Condition(
            name="test_condition",
            evaluator=True,
            steps=[Step(name="if_step", executor=if_step_func)],
            else_steps=[Step(name="else_step", executor=else_step_func)],
        )

        step_input = StepInput(input="test")
        result = condition.execute(step_input, force_else_branch=False)

        # Should execute if branch
        assert "if branch" in result.content.lower()

    def test_condition_normal_execution_else_branch(self):
        """Test Condition normal execution takes else branch when evaluator is False."""
        from agno.workflow.condition import Condition

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def else_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="ELSE branch executed")

        condition = Condition(
            name="test_condition",
            evaluator=False,
            steps=[Step(name="if_step", executor=if_step_func)],
            else_steps=[Step(name="else_step", executor=else_step_func)],
        )

        step_input = StepInput(input="test")
        result = condition.execute(step_input, force_else_branch=False)

        # Should execute else branch
        assert "else branch" in result.content.lower()

    def test_condition_to_dict_includes_on_reject(self):
        """Test that Condition.to_dict includes on_reject field."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        condition = Condition(
            name="test_condition",
            steps=[Step(name="if_step", executor=fetch_data)],
            requires_confirmation=True,
            on_reject=OnReject.else_branch,
        )

        data = condition.to_dict()

        assert "on_reject" in data
        assert data["on_reject"] == "OnReject.else_branch" or data["on_reject"] == "else"

    def test_condition_from_dict_restores_on_reject(self):
        """Test that Condition.from_dict restores on_reject field."""
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject

        data = {
            "type": "Condition",
            "name": "test_condition",
            "evaluator": True,
            "evaluator_type": "bool",
            "steps": [],
            "else_steps": [],
            "requires_confirmation": True,
            "on_reject": "skip",
        }

        condition = Condition.from_dict(data)

        assert condition.on_reject == "skip" or condition.on_reject == OnReject.skip

    def test_step_requirement_on_reject_else_only_for_condition(self):
        """Test that on_reject='else' is validated for Condition step type."""
        # Create a StepRequirement with on_reject='else' but non-Condition type
        req = StepRequirement(
            step_id="step-1",
            step_name="regular_step",
            step_index=0,
            step_type="Step",  # Not a Condition
            requires_confirmation=True,
            on_reject="else",  # This should be invalid for non-Condition
        )

        # The requirement can be created, but workflow.py should warn/fallback
        assert req.on_reject == "else"
        assert req.step_type == "Step"


class TestConditionOnRejectWorkflowIntegration:
    """Integration tests for Condition on_reject with Workflow."""

    def test_condition_on_reject_else_executes_else_branch(self):
        """Test that rejecting a Condition with on_reject='else' executes else_steps."""
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject
        from agno.workflow.workflow import Workflow

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def else_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="ELSE branch executed")

        def final_step_func(step_input: StepInput) -> StepOutput:
            previous = step_input.previous_step_content or "nothing"
            return StepOutput(content=f"Final step. Previous: {previous}")

        condition = Condition(
            name="user_choice",
            steps=[Step(name="if_step", executor=if_step_func)],
            else_steps=[Step(name="else_step", executor=else_step_func)],
            requires_confirmation=True,
            on_reject=OnReject.else_branch,
        )

        workflow = Workflow(
            name="test_workflow",
            steps=[condition, Step(name="final_step", executor=final_step_func)],
            db=SqliteDb(db_file="tmp/test_condition_on_reject.db"),
        )

        # Run workflow - should pause at condition
        run_output = workflow.run("test input")
        assert run_output.is_paused
        assert len(run_output.steps_requiring_confirmation) == 1

        req = run_output.steps_requiring_confirmation[0]
        assert req.step_name == "user_choice"
        assert req.on_reject == "else"

        # Reject the condition
        req.reject()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

        # Should complete and else branch should have been executed
        assert run_output.status == RunStatus.completed
        # The final step should have received content from else_step
        assert "ELSE branch executed" in str(run_output.content) or any(
            "ELSE branch executed" in str(r.content) for r in (run_output.step_results or [])
        )

    def test_condition_on_reject_skip_skips_entire_condition(self):
        """Test that rejecting a Condition with on_reject='skip' skips both branches."""
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject
        from agno.workflow.workflow import Workflow

        def setup_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Setup complete")

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def else_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="ELSE branch executed")

        def final_step_func(step_input: StepInput) -> StepOutput:
            previous = step_input.previous_step_content or "nothing"
            return StepOutput(content=f"Final step. Previous: {previous}")

        condition = Condition(
            name="skippable_condition",
            steps=[Step(name="if_step", executor=if_step_func)],
            else_steps=[Step(name="else_step", executor=else_step_func)],
            requires_confirmation=True,
            on_reject=OnReject.skip,
        )

        workflow = Workflow(
            name="test_workflow",
            steps=[
                Step(name="setup_step", executor=setup_step_func),
                condition,
                Step(name="final_step", executor=final_step_func),
            ],
            db=SqliteDb(db_file="tmp/test_condition_skip.db"),
        )

        # Run workflow - should pause at condition
        run_output = workflow.run("test input")
        assert run_output.is_paused

        req = run_output.steps_requiring_confirmation[0]
        assert req.on_reject == "skip"

        # Reject the condition
        req.reject()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

        # Should complete
        assert run_output.status == RunStatus.completed

        # Neither if nor else branch should have executed
        step_names = [r.step_name for r in (run_output.step_results or [])]
        assert "if_step" not in step_names
        assert "else_step" not in step_names

        # final_step should have "Setup complete" as previous (skipped condition)
        assert "Setup complete" in str(run_output.content)

    def test_condition_on_reject_cancel_cancels_workflow(self):
        """Test that rejecting a Condition with on_reject='cancel' cancels the workflow."""
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject
        from agno.workflow.workflow import Workflow

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        condition = Condition(
            name="critical_condition",
            steps=[Step(name="if_step", executor=if_step_func)],
            requires_confirmation=True,
            on_reject=OnReject.cancel,
        )

        workflow = Workflow(
            name="test_workflow",
            steps=[condition],
            db=SqliteDb(db_file="tmp/test_condition_cancel.db"),
        )

        # Run workflow - should pause at condition
        run_output = workflow.run("test input")
        assert run_output.is_paused

        req = run_output.steps_requiring_confirmation[0]
        assert req.on_reject == "cancel"

        # Reject the condition
        req.reject()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

        # Should be cancelled
        assert run_output.status == RunStatus.cancelled
        assert "rejected" in str(run_output.content).lower() or "cancelled" in str(run_output.content).lower()

    def test_condition_confirm_executes_if_branch(self):
        """Test that confirming a Condition executes the if branch."""
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject
        from agno.workflow.workflow import Workflow

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def else_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="ELSE branch executed")

        condition = Condition(
            name="user_choice",
            steps=[Step(name="if_step", executor=if_step_func)],
            else_steps=[Step(name="else_step", executor=else_step_func)],
            requires_confirmation=True,
            on_reject=OnReject.else_branch,
        )

        workflow = Workflow(
            name="test_workflow",
            steps=[condition],
            db=SqliteDb(db_file="tmp/test_condition_confirm.db"),
        )

        # Run workflow - should pause at condition
        run_output = workflow.run("test input")
        assert run_output.is_paused

        req = run_output.steps_requiring_confirmation[0]

        # Confirm the condition
        req.confirm()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

        # Should complete and if branch should have been executed
        assert run_output.status == RunStatus.completed
        # Check if_step was executed
        step_contents = [str(r.content) for r in (run_output.step_results or [])]
        assert any("IF branch executed" in c for c in step_contents) or "if branch" in str(run_output.content).lower()

    def test_condition_on_reject_else_no_else_steps_skips(self):
        """Test on_reject='else' with no else_steps skips the condition."""
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.types import OnReject
        from agno.workflow.workflow import Workflow

        def if_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="IF branch executed")

        def final_step_func(step_input: StepInput) -> StepOutput:
            return StepOutput(content="Final step executed")

        condition = Condition(
            name="no_else_condition",
            steps=[Step(name="if_step", executor=if_step_func)],
            # No else_steps!
            requires_confirmation=True,
            on_reject=OnReject.else_branch,
        )

        workflow = Workflow(
            name="test_workflow",
            steps=[condition, Step(name="final_step", executor=final_step_func)],
            db=SqliteDb(db_file="tmp/test_condition_no_else.db"),
        )

        # Run workflow - should pause at condition
        run_output = workflow.run("test input")
        assert run_output.is_paused

        req = run_output.steps_requiring_confirmation[0]

        # Reject the condition (with on_reject='else' but no else_steps)
        req.reject()

        # Continue the workflow
        run_output = workflow.continue_run(run_output)

        # Should complete - condition should be skipped since no else_steps
        assert run_output.status == RunStatus.completed

        # if_step should NOT have executed
        step_names = [r.step_name for r in (run_output.step_results or [])]
        assert "if_step" not in step_names

        # final_step should have executed
        assert "final_step" in step_names or "Final step executed" in str(run_output.content)
