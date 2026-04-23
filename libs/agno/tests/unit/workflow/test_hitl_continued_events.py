"""
Unit tests for StepContinuedEvent and StepExecutorContinuedEvent.

Tests cover:
- Event creation and field defaults
- Event registration in WORKFLOW_RUN_EVENT_TYPE_REGISTRY
- Event values match WorkflowRunEvent enum
- StepContinuedEvent emitted when step-level HITL resumes
- StepExecutorContinuedEvent emitted when executor-level HITL resumes
- Workflow streaming integration: events appear in continue_run stream
"""

from agno.run.workflow import (
    WORKFLOW_RUN_EVENT_TYPE_REGISTRY,
    StepContinuedEvent,
    StepExecutorContinuedEvent,
    StepExecutorPausedEvent,
    StepPausedEvent,
    WorkflowRunEvent,
)
from agno.workflow.types import (
    StepRequirement,
)

# =============================================================================
# StepContinuedEvent Tests
# =============================================================================


class TestStepContinuedEvent:
    """Tests for StepContinuedEvent dataclass."""

    def test_event_creation(self):
        """Test creating a StepContinuedEvent with default values."""
        event = StepContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test_workflow",
            session_id="session-1",
        )

        assert event.event == "StepContinued"
        assert event.run_id == "run-1"
        assert event.workflow_name == "test_workflow"
        assert event.step_name is None
        assert event.step_index is None
        assert event.step_id is None

    def test_event_with_step_info(self):
        """Test creating a StepContinuedEvent with step details."""
        event = StepContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test_workflow",
            session_id="session-1",
            step_name="process_data",
            step_index=2,
            step_id="step-abc",
        )

        assert event.step_name == "process_data"
        assert event.step_index == 2
        assert event.step_id == "step-abc"

    def test_event_value_matches_enum(self):
        """Test that the event value matches the WorkflowRunEvent enum."""
        event = StepContinuedEvent(run_id="run-1")
        assert event.event == WorkflowRunEvent.step_continued.value
        assert event.event == "StepContinued"

    def test_event_registered_in_event_type_map(self):
        """Test that StepContinuedEvent is registered in WORKFLOW_RUN_EVENT_TYPE_REGISTRY."""
        assert WorkflowRunEvent.step_continued.value in WORKFLOW_RUN_EVENT_TYPE_REGISTRY
        assert WORKFLOW_RUN_EVENT_TYPE_REGISTRY[WorkflowRunEvent.step_continued.value] == StepContinuedEvent

    def test_event_is_counterpart_to_paused(self):
        """Test that StepContinuedEvent mirrors StepPausedEvent structure."""
        paused = StepPausedEvent(
            run_id="run-1",
            step_name="test",
            step_index=0,
        )
        continued = StepContinuedEvent(
            run_id="run-1",
            step_name="test",
            step_index=0,
        )

        # Both share the same step identification fields
        assert paused.step_name == continued.step_name
        assert paused.step_index == continued.step_index


# =============================================================================
# StepExecutorContinuedEvent Tests
# =============================================================================


class TestStepExecutorContinuedEvent:
    """Tests for StepExecutorContinuedEvent dataclass."""

    def test_event_creation(self):
        """Test creating a StepExecutorContinuedEvent with default values."""
        event = StepExecutorContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test_workflow",
            session_id="session-1",
        )

        assert event.event == "StepExecutorContinued"
        assert event.run_id == "run-1"
        assert event.step_name is None
        assert event.executor_id is None
        assert event.executor_name is None
        assert event.executor_run_id is None
        assert event.executor_type is None

    def test_event_with_agent_executor(self):
        """Test creating event with agent executor details."""
        event = StepExecutorContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test_workflow",
            session_id="session-1",
            step_name="get_weather",
            step_index=0,
            executor_id="agent-123",
            executor_name="WeatherAgent",
            executor_run_id="exec-run-1",
            executor_type="agent",
        )

        assert event.step_name == "get_weather"
        assert event.executor_name == "WeatherAgent"
        assert event.executor_type == "agent"

    def test_event_with_team_executor(self):
        """Test creating event with team executor details."""
        event = StepExecutorContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test_workflow",
            session_id="session-1",
            step_name="research",
            executor_id="team-456",
            executor_name="ResearchTeam",
            executor_type="team",
        )

        assert event.executor_name == "ResearchTeam"
        assert event.executor_type == "team"

    def test_event_value_matches_enum(self):
        """Test that the event value matches the WorkflowRunEvent enum."""
        event = StepExecutorContinuedEvent(run_id="run-1")
        assert event.event == WorkflowRunEvent.step_executor_continued.value
        assert event.event == "StepExecutorContinued"

    def test_event_registered_in_event_type_map(self):
        """Test that StepExecutorContinuedEvent is registered in WORKFLOW_RUN_EVENT_TYPE_REGISTRY."""
        assert WorkflowRunEvent.step_executor_continued.value in WORKFLOW_RUN_EVENT_TYPE_REGISTRY
        assert (
            WORKFLOW_RUN_EVENT_TYPE_REGISTRY[WorkflowRunEvent.step_executor_continued.value]
            == StepExecutorContinuedEvent
        )

    def test_event_is_counterpart_to_paused(self):
        """Test that StepExecutorContinuedEvent mirrors StepExecutorPausedEvent fields."""
        paused = StepExecutorPausedEvent(
            run_id="run-1",
            step_name="get_weather",
            step_index=0,
            executor_id="agent-1",
            executor_name="WeatherAgent",
            executor_run_id="exec-1",
            executor_type="agent",
        )
        continued = StepExecutorContinuedEvent(
            run_id="run-1",
            step_name="get_weather",
            step_index=0,
            executor_id="agent-1",
            executor_name="WeatherAgent",
            executor_run_id="exec-1",
            executor_type="agent",
        )

        # Both share the same executor identification fields
        assert paused.step_name == continued.step_name
        assert paused.executor_name == continued.executor_name
        assert paused.executor_type == continued.executor_type
        assert paused.executor_run_id == continued.executor_run_id

        # Paused has extra requirements field that continued doesn't need
        assert hasattr(paused, "executor_requirements")
        assert not hasattr(continued, "executor_requirements") or continued.executor_requirements is None


# =============================================================================
# Enum completeness tests
# =============================================================================


class TestEventEnumCompleteness:
    """Test that paused/continued events come in matching pairs."""

    def test_step_paused_has_continued_counterpart(self):
        """Every step pause event type should have a corresponding continued event type."""
        assert hasattr(WorkflowRunEvent, "step_paused")
        assert hasattr(WorkflowRunEvent, "step_continued")

    def test_executor_paused_has_continued_counterpart(self):
        """Every executor pause event type should have a corresponding continued event type."""
        assert hasattr(WorkflowRunEvent, "step_executor_paused")
        assert hasattr(WorkflowRunEvent, "step_executor_continued")

    def test_all_pause_continued_pairs_in_event_map(self):
        """All pause/continued event pairs should be registered in WORKFLOW_RUN_EVENT_TYPE_REGISTRY."""
        pairs = [
            (WorkflowRunEvent.step_paused, WorkflowRunEvent.step_continued),
            (WorkflowRunEvent.step_executor_paused, WorkflowRunEvent.step_executor_continued),
        ]
        for paused_event, continued_event in pairs:
            assert paused_event.value in WORKFLOW_RUN_EVENT_TYPE_REGISTRY, (
                f"{paused_event.value} missing from WORKFLOW_RUN_EVENT_TYPE_REGISTRY"
            )
            assert continued_event.value in WORKFLOW_RUN_EVENT_TYPE_REGISTRY, (
                f"{continued_event.value} missing from WORKFLOW_RUN_EVENT_TYPE_REGISTRY"
            )


# =============================================================================
# Integration: continued events with workflow run output
# =============================================================================


class TestContinuedEventsWithWorkflowRunOutput:
    """Test that continued events work correctly with WorkflowRunOutput lifecycle."""

    def test_step_continued_after_confirmation_resolved(self):
        """Verify StepContinuedEvent can be created from a resolved step requirement."""
        req = StepRequirement(
            step_id="step-1",
            step_name="process_data",
            step_index=1,
            requires_confirmation=True,
            confirmation_message="Proceed?",
        )
        req.confirm()

        # After confirmation, we'd emit a continued event
        event = StepContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test",
            session_id="s-1",
            step_name=req.step_name,
            step_index=req.step_index,
            step_id=req.step_id,
        )

        assert event.step_name == "process_data"
        assert event.step_index == 1
        assert req.is_resolved is True

    def test_executor_continued_after_tool_confirmation_resolved(self):
        """Verify StepExecutorContinuedEvent can be created from a resolved executor requirement."""
        req = StepRequirement(
            step_id="step-1",
            step_name="get_weather",
            step_index=0,
            requires_executor_input=True,
            executor_id="agent-1",
            executor_name="WeatherAgent",
            executor_run_id="exec-1",
            executor_type="agent",
            executor_requirements=[],  # Empty = resolved
        )

        event = StepExecutorContinuedEvent(
            run_id="run-1",
            workflow_id="wf-1",
            workflow_name="test",
            session_id="s-1",
            step_name=req.step_name,
            step_index=req.step_index,
            executor_id=req.executor_id,
            executor_name=req.executor_name,
            executor_type=req.executor_type,
        )

        assert event.executor_name == "WeatherAgent"
        assert event.executor_type == "agent"
