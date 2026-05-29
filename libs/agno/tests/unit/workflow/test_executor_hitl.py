"""
Unit tests for Executor HITL (Human-In-The-Loop) in workflows.

Tests cover:
- StepOutput.is_paused flag
- StepRequirement executor fields (serialization/deserialization)
- StepRequirement.needs_executor_resolution property
- StepRequirement.is_resolved with executor requirements
- Step._create_executor_step_requirement helper
- WorkflowRunOutput.steps_requiring_executor_resolution property
- StepExecutorPausedEvent
- Parallel step guard for executor HITL
"""

from unittest.mock import MagicMock

from agno.run.workflow import (
    StepExecutorPausedEvent,
    WorkflowRunEvent,
    WorkflowRunOutput,
)
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import (
    StepOutput,
    StepRequirement,
    StepType,
)

# =============================================================================
# StepOutput.is_paused Tests
# =============================================================================


class TestStepOutputPaused:
    """Tests for StepOutput.is_paused flag."""

    def test_step_output_default_not_paused(self):
        """StepOutput.is_paused defaults to False."""
        output = StepOutput(content="test")
        assert output.is_paused is False

    def test_step_output_paused_flag(self):
        """StepOutput can carry is_paused=True."""
        output = StepOutput(content="test", is_paused=True)
        assert output.is_paused is True

    def test_step_output_executor_run_response(self):
        """StepOutput can carry _executor_run_response as a runtime attribute."""
        mock_response = MagicMock()
        output = StepOutput(content="test", is_paused=True)
        output._executor_run_response = mock_response
        assert output._executor_run_response is mock_response

    def test_step_output_to_dict_excludes_executor_response(self):
        """StepOutput.to_dict() does not include _executor_run_response."""
        mock_response = MagicMock()
        output = StepOutput(content="test", is_paused=True)
        output._executor_run_response = mock_response
        d = output.to_dict()
        assert "is_paused" in d
        assert d["is_paused"] is True
        assert "_executor_run_response" not in d

    def test_step_output_from_dict_with_paused(self):
        """StepOutput.from_dict() can deserialize is_paused."""
        d = {"content": "test", "is_paused": True}
        output = StepOutput.from_dict(d)
        assert output.is_paused is True

    def test_step_output_from_dict_without_paused(self):
        """StepOutput.from_dict() defaults is_paused to False."""
        d = {"content": "test"}
        output = StepOutput.from_dict(d)
        assert output.is_paused is False


# =============================================================================
# StepRequirement Executor Fields Tests
# =============================================================================


class TestStepRequirementExecutorFields:
    """Tests for executor HITL fields on StepRequirement."""

    def test_default_values(self):
        """Executor fields default to False/None."""
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
        )
        assert req.requires_executor_input is False
        assert req.executor_requirements is None
        assert req.executor_id is None
        assert req.executor_name is None
        assert req.executor_run_id is None
        assert req.executor_type is None

    def test_executor_fields_set(self):
        """Executor fields can be set."""
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
            requires_executor_input=True,
            executor_requirements=[{"id": "r1", "tool_execution": {}}],
            executor_id="agent-1",
            executor_name="TestAgent",
            executor_run_id="run-1",
            executor_type="agent",
        )
        assert req.requires_executor_input is True
        assert req.executor_requirements == [{"id": "r1", "tool_execution": {}}]
        assert req.executor_id == "agent-1"
        assert req.executor_name == "TestAgent"
        assert req.executor_run_id == "run-1"
        assert req.executor_type == "agent"

    def test_needs_executor_resolution_true(self):
        """needs_executor_resolution is True when an underlying RunRequirement is unresolved."""
        pending = {"tool_execution": {"tool_name": "x", "tool_args": {}, "requires_confirmation": True}}
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
            requires_executor_input=True,
            executor_requirements=[pending],
        )
        assert req.needs_executor_resolution is True

    def test_needs_executor_resolution_false_all_resolved(self):
        """needs_executor_resolution is False once all underlying RunRequirements are resolved."""
        resolved = {
            "tool_execution": {
                "tool_name": "x",
                "tool_args": {},
                "requires_confirmation": True,
                "confirmed": True,
            }
        }
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
            requires_executor_input=True,
            executor_requirements=[resolved],
        )
        assert req.needs_executor_resolution is False

    def test_needs_executor_resolution_false_no_requirements(self):
        """needs_executor_resolution is False when executor_requirements is None."""
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
            requires_executor_input=True,
            executor_requirements=None,
        )
        assert req.needs_executor_resolution is False

    def test_needs_executor_resolution_false_no_flag(self):
        """needs_executor_resolution is False when requires_executor_input is False."""
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
            requires_executor_input=False,
            executor_requirements=[{"id": "r1"}],
        )
        assert req.needs_executor_resolution is False

    def test_to_dict_with_executor_fields(self):
        """to_dict() serializes executor fields when requires_executor_input is True."""
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
            step_type=StepType.STEP,
            requires_executor_input=True,
            executor_requirements=[{"id": "r1", "confirmation": True}],
            executor_id="agent-1",
            executor_name="TestAgent",
            executor_run_id="run-1",
            executor_type="agent",
        )
        d = req.to_dict()
        assert d["requires_executor_input"] is True
        assert d["executor_requirements"] == [{"id": "r1", "confirmation": True}]
        assert d["executor_id"] == "agent-1"
        assert d["executor_name"] == "TestAgent"
        assert d["executor_run_id"] == "run-1"
        assert d["executor_type"] == "agent"
        assert "_executor_run_response" not in d

    def test_to_dict_without_executor_fields(self):
        """to_dict() does not include executor fields when requires_executor_input is False."""
        req = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=0,
        )
        d = req.to_dict()
        assert "requires_executor_input" not in d or d.get("requires_executor_input") is False

    def test_from_dict_with_executor_fields(self):
        """from_dict() deserializes executor fields."""
        d = {
            "step_id": "s1",
            "step_name": "test",
            "step_index": 0,
            "step_type": "Step",
            "requires_executor_input": True,
            "executor_requirements": [{"id": "r1"}],
            "executor_id": "agent-1",
            "executor_name": "TestAgent",
            "executor_run_id": "run-1",
            "executor_type": "agent",
        }
        req = StepRequirement.from_dict(d)
        assert req.requires_executor_input is True
        assert req.executor_requirements == [{"id": "r1"}]
        assert req.executor_id == "agent-1"
        assert req.executor_name == "TestAgent"
        assert req.executor_run_id == "run-1"
        assert req.executor_type == "agent"

    def test_from_dict_without_executor_fields(self):
        """from_dict() defaults executor fields to False/None."""
        d = {
            "step_id": "s1",
            "step_name": "test",
            "step_index": 0,
        }
        req = StepRequirement.from_dict(d)
        assert req.requires_executor_input is False
        assert req.executor_requirements is None
        assert req.executor_id is None

    def test_roundtrip_serialization(self):
        """Executor fields survive to_dict() -> from_dict() roundtrip."""
        original = StepRequirement(
            step_id="s1",
            step_name="test",
            step_index=2,
            step_type=StepType.STEP,
            requires_executor_input=True,
            executor_requirements=[{"id": "r1", "confirmation": True}],
            executor_id="agent-abc",
            executor_name="MyAgent",
            executor_run_id="run-xyz",
            executor_type="team",
        )
        restored = StepRequirement.from_dict(original.to_dict())
        assert restored.requires_executor_input == original.requires_executor_input
        assert restored.executor_requirements == original.executor_requirements
        assert restored.executor_id == original.executor_id
        assert restored.executor_name == original.executor_name
        assert restored.executor_run_id == original.executor_run_id
        assert restored.executor_type == original.executor_type


# =============================================================================
# Step._create_executor_step_requirement Tests
# =============================================================================


class TestCreateExecutorStepRequirement:
    """Tests for Step._create_executor_step_requirement helper."""

    def test_creates_requirement_for_agent(self):
        """Creates correct StepRequirement from a paused agent response."""
        mock_agent = MagicMock()
        mock_agent.id = None  # Agent uses agent_id, not id
        mock_agent.agent_id = "agent-123"
        mock_agent.name = "TestAgent"

        step = Step(name="test_step", agent=mock_agent)
        step.step_id = "step-456"

        # Mock executor response
        mock_response = MagicMock()
        mock_response.run_id = "run-789"
        mock_req = MagicMock()
        mock_req.to_dict.return_value = {"id": "r1", "confirmation": True}
        mock_response.requirements = [mock_req]

        req = step._create_executor_step_requirement(step_index=1, executor_response=mock_response)

        assert req.step_id == "step-456"
        assert req.step_name == "test_step"
        assert req.step_index == 1
        assert req.step_type == StepType.STEP
        assert req.requires_executor_input is True
        assert req.executor_requirements == [{"id": "r1", "confirmation": True}]
        assert req.executor_id == "agent-123"
        assert req.executor_name == "TestAgent"
        assert req.executor_run_id == "run-789"
        assert req.executor_type == "agent"

    def test_creates_requirement_for_team(self):
        """Creates correct StepRequirement for team executor."""
        from agno.team.team import Team

        mock_team = MagicMock(spec=Team)
        mock_team.id = "team-123"
        mock_team.name = "TestTeam"

        step = Step(name="team_step", team=mock_team)
        step.step_id = "step-789"

        mock_response = MagicMock()
        mock_response.run_id = "run-abc"
        mock_response.requirements = []

        req = step._create_executor_step_requirement(step_index=0, executor_response=mock_response)

        assert req.executor_type == "team"
        assert req.executor_id == "team-123"
        assert req.executor_name == "TestTeam"
        assert req.executor_requirements == []

    def test_handles_none_requirements(self):
        """Handles executor response with no requirements."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "agent-1"
        mock_agent.name = "Agent"

        step = Step(name="test", agent=mock_agent)
        step.step_id = "s1"

        mock_response = MagicMock()
        mock_response.run_id = "r1"
        mock_response.requirements = None

        req = step._create_executor_step_requirement(step_index=0, executor_response=mock_response)

        assert req.executor_requirements == []

    def test_generates_step_id_if_none(self):
        """Generates a step_id if none is set."""
        mock_agent = MagicMock()
        mock_agent.agent_id = "a1"
        mock_agent.name = "A"

        step = Step(name="test", agent=mock_agent)
        step.step_id = None

        mock_response = MagicMock()
        mock_response.run_id = "r1"
        mock_response.requirements = []

        req = step._create_executor_step_requirement(step_index=0, executor_response=mock_response)

        assert req.step_id is not None
        assert len(req.step_id) > 0


# =============================================================================
# WorkflowRunOutput Executor Properties Tests
# =============================================================================


class TestWorkflowRunOutputExecutorProperties:
    """Tests for WorkflowRunOutput executor HITL properties."""

    def test_steps_requiring_executor_resolution_empty(self):
        """Returns empty list when no step_requirements."""
        output = WorkflowRunOutput()
        assert output.steps_requiring_executor_resolution == []

    def test_steps_requiring_executor_resolution_none(self):
        """Returns empty list when step_requirements is None."""
        output = WorkflowRunOutput()
        output.step_requirements = None
        assert output.steps_requiring_executor_resolution == []

    def test_steps_requiring_executor_resolution_filters(self):
        """Returns only requirements that need executor resolution."""
        req1 = StepRequirement(
            step_id="s1",
            step_name="normal",
            step_index=0,
            requires_confirmation=True,
        )
        req2 = StepRequirement(
            step_id="s2",
            step_name="executor",
            step_index=1,
            requires_executor_input=True,
            executor_requirements=[
                {"tool_execution": {"tool_name": "x", "tool_args": {}, "requires_confirmation": True}}
            ],
        )
        output = WorkflowRunOutput()
        output.step_requirements = [req1, req2]

        result = output.steps_requiring_executor_resolution
        assert len(result) == 1
        assert result[0].step_name == "executor"


# =============================================================================
# StepExecutorPausedEvent Tests
# =============================================================================


class TestStepExecutorPausedEvent:
    """Tests for StepExecutorPausedEvent."""

    def test_event_type(self):
        """Event has correct type."""
        event = StepExecutorPausedEvent(
            run_id="r1",
            workflow_name="wf",
            workflow_id="wf-1",
            session_id="s1",
        )
        assert event.event == WorkflowRunEvent.step_executor_paused.value

    def test_event_fields(self):
        """Event carries executor context."""
        event = StepExecutorPausedEvent(
            run_id="r1",
            workflow_name="wf",
            workflow_id="wf-1",
            session_id="s1",
            step_name="my_step",
            step_index=2,
            step_id="step-abc",
            executor_id="agent-1",
            executor_name="TestAgent",
            executor_run_id="run-xyz",
            executor_type="agent",
            executor_requirements=[{"id": "r1"}],
        )
        assert event.step_name == "my_step"
        assert event.step_index == 2
        assert event.executor_id == "agent-1"
        assert event.executor_type == "agent"
        assert event.executor_requirements == [{"id": "r1"}]

    def test_event_in_registry(self):
        """StepExecutorPaused event is in the event type registry."""
        from agno.run.workflow import WORKFLOW_RUN_EVENT_TYPE_REGISTRY

        assert WorkflowRunEvent.step_executor_paused.value in WORKFLOW_RUN_EVENT_TYPE_REGISTRY

    def test_event_serialization(self):
        """Event can be serialized to dict."""
        event = StepExecutorPausedEvent(
            run_id="r1",
            workflow_name="wf",
            workflow_id="wf-1",
            session_id="s1",
            executor_name="TestAgent",
        )
        d = event.to_dict()
        assert d["event"] == "StepExecutorPaused"
        assert d["executor_name"] == "TestAgent"


# =============================================================================
# Parallel Step Guard Tests
# =============================================================================


class TestParallelExecutorHITLGuard:
    """Tests for Parallel step guard against executor HITL."""

    def test_aggregate_raises_on_paused_output(self):
        """_aggregate_results raises ValueError when a step output is paused."""
        parallel = Parallel(name="test_parallel")

        outputs = [
            StepOutput(step_name="step1", content="ok"),
            StepOutput(step_name="step2", content="paused", is_paused=True),
        ]

        import pytest

        with pytest.raises(ValueError, match="Executor HITL inside Parallel steps is not supported"):
            parallel._aggregate_results(outputs)

    def test_aggregate_passes_without_paused(self):
        """_aggregate_results works normally when no step is paused."""
        parallel = Parallel(name="test_parallel")

        outputs = [
            StepOutput(step_name="step1", content="ok"),
            StepOutput(step_name="step2", content="also ok"),
        ]

        result = parallel._aggregate_results(outputs)
        assert result.step_name == "test_parallel"
        assert result.is_paused is False
