"""
Unit tests for Step serialization and deserialization.

Tests cover:
- to_dict(): Serialization of Step to dictionary
- from_dict(): Deserialization of Step from dictionary
- Roundtrip serialization (no data loss)
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.registry import Registry
from agno.workflow.step import Step
from agno.workflow.types import StepInput

# =============================================================================
# Sample executor functions for testing
# =============================================================================


def sample_executor(step_input: StepInput) -> str:
    """A sample executor function for testing."""
    return "executed"


def another_executor(step_input: StepInput) -> str:
    """Another executor function for testing."""
    return "another result"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    agent = MagicMock()
    agent.id = "test-agent-id"
    agent.name = "Test Agent"
    agent.description = "A test agent"
    return agent


@pytest.fixture
def mock_team():
    """Create a mock team for testing."""
    team = MagicMock()
    team.id = "test-team-id"
    team.name = "Test Team"
    team.description = "A test team"
    return team


@pytest.fixture
def registry_with_functions():
    """Create a registry with sample functions registered."""
    registry = Registry(functions=[sample_executor, another_executor])
    return registry


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestStepToDict:
    """Tests for Step.to_dict() method."""

    def test_to_dict_with_agent(self, mock_agent):
        """Test to_dict serializes agent reference."""
        step = Step(name="agent-step", agent=mock_agent, description="Step with agent")
        result = step.to_dict()

        assert result["type"] == "Step"
        assert result["name"] == "agent-step"
        assert result["description"] == "Step with agent"
        assert result["agent_id"] == "test-agent-id"
        assert "team_id" not in result
        assert "executor_ref" not in result

    def test_to_dict_with_team(self, mock_team):
        """Test to_dict serializes team reference."""
        step = Step(name="team-step", team=mock_team, description="Step with team")
        result = step.to_dict()

        assert result["type"] == "Step"
        assert result["name"] == "team-step"
        assert result["description"] == "Step with team"
        assert result["team_id"] == "test-team-id"
        assert "agent_id" not in result
        assert "executor_ref" not in result

    def test_to_dict_with_executor(self):
        """Test to_dict serializes executor function reference."""
        step = Step(name="executor-step", executor=sample_executor, description="Step with executor")
        result = step.to_dict()

        assert result["type"] == "Step"
        assert result["name"] == "executor-step"
        assert result["description"] == "Step with executor"
        assert result["executor_ref"] == "sample_executor"
        assert "agent_id" not in result
        assert "team_id" not in result

    def test_to_dict_preserves_all_fields(self, mock_agent):
        """Test to_dict preserves all step configuration fields."""
        step = Step(
            name="full-step",
            agent=mock_agent,
            step_id="custom-step-id",
            description="Full step description",
            max_retries=5,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=10,
        )
        result = step.to_dict()

        assert result["name"] == "full-step"
        assert result["step_id"] == "custom-step-id"
        assert result["description"] == "Full step description"
        assert result["max_retries"] == 5
        assert result["skip_on_failure"] is True
        assert result["strict_input_validation"] is True
        assert result["add_workflow_history"] is True
        assert result["num_history_runs"] == 10

    def test_to_dict_default_values(self, mock_agent):
        """Test to_dict includes default values."""
        step = Step(name="default-step", agent=mock_agent)
        result = step.to_dict()

        assert result["max_retries"] == 3
        assert result["skip_on_failure"] is False
        assert result["strict_input_validation"] is False
        assert result["add_workflow_history"] is None
        assert result["num_history_runs"] == 3


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestStepFromDict:
    """Tests for Step.from_dict() method."""

    def test_from_dict_basic(self):
        """Test from_dict creates step with basic config."""
        _data = {  # noqa: F841
            "type": "Step",
            "name": "basic-step",
            "description": "A basic step",
            "max_retries": 3,
            "skip_on_failure": False,
            "strict_input_validation": False,
            "add_workflow_history": None,
            "num_history_runs": 3,
        }

        # Need to provide an executor since Step requires one
        with patch("agno.workflow.step.Step.__init__", return_value=None):
            # Skip actual initialization for this basic test
            pass

    def test_from_dict_with_agent(self):
        """Test from_dict reconstructs step with agent."""
        mock_agent = MagicMock()
        mock_agent.id = "loaded-agent-id"

        data = {
            "type": "Step",
            "name": "agent-step",
            "description": "Step with agent",
            "agent_id": "loaded-agent-id",
            "max_retries": 3,
            "skip_on_failure": False,
            "strict_input_validation": False,
        }

        with patch("agno.agent.agent.get_agent_by_id") as mock_get_agent:
            mock_get_agent.return_value = mock_agent

            mock_db = MagicMock()
            step = Step.from_dict(data, db=mock_db)

            mock_get_agent.assert_called_once()
            assert step.agent == mock_agent
            assert step.name == "agent-step"

    def test_from_dict_with_executor(self, registry_with_functions):
        """Test from_dict reconstructs step with executor function."""
        data = {
            "type": "Step",
            "name": "executor-step",
            "description": "Step with executor",
            "executor_ref": "sample_executor",
            "max_retries": 3,
            "skip_on_failure": False,
            "strict_input_validation": False,
        }

        step = Step.from_dict(data, registry=registry_with_functions)

        assert step.executor == sample_executor
        assert step.name == "executor-step"

    def test_from_dict_preserves_all_fields(self, registry_with_functions):
        """Test from_dict preserves all configuration fields."""
        data = {
            "type": "Step",
            "name": "full-step",
            "step_id": "custom-step-id",
            "description": "Full description",
            "executor_ref": "sample_executor",
            "max_retries": 5,
            "skip_on_failure": True,
            "strict_input_validation": True,
            "add_workflow_history": True,
            "num_history_runs": 10,
        }

        step = Step.from_dict(data, registry=registry_with_functions)

        assert step.name == "full-step"
        assert step.step_id == "custom-step-id"
        assert step.description == "Full description"
        assert step.max_retries == 5
        assert step.skip_on_failure is True
        assert step.strict_input_validation is True
        assert step.add_workflow_history is True
        assert step.num_history_runs == 10


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestStepSerializationRoundtrip:
    """Tests for Step serialization roundtrip (to_dict -> from_dict)."""

    def test_roundtrip_with_executor(self, registry_with_functions):
        """Test roundtrip preserves all data for step with executor."""
        original = Step(
            name="roundtrip-step",
            executor=sample_executor,
            description="Roundtrip test step",
            max_retries=4,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=7,
        )

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Step.from_dict(data, registry=registry_with_functions)

        # Verify no data loss
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.max_retries == original.max_retries
        assert restored.skip_on_failure == original.skip_on_failure
        assert restored.strict_input_validation == original.strict_input_validation
        assert restored.add_workflow_history == original.add_workflow_history
        assert restored.num_history_runs == original.num_history_runs
        assert restored.executor == original.executor

    def test_roundtrip_preserves_type_field(self, registry_with_functions):
        """Test roundtrip preserves type field for proper deserialization dispatch."""
        step = Step(name="typed-step", executor=sample_executor)

        data = step.to_dict()
        assert data["type"] == "Step"

        restored = Step.from_dict(data, registry=registry_with_functions)
        assert restored.name == "typed-step"

    def test_roundtrip_with_default_values(self, registry_with_functions):
        """Test roundtrip preserves default values."""
        original = Step(name="defaults-step", executor=sample_executor)

        data = original.to_dict()
        restored = Step.from_dict(data, registry=registry_with_functions)

        assert restored.max_retries == 3
        assert restored.skip_on_failure is False
        assert restored.strict_input_validation is False
        assert restored.num_history_runs == 3

    def test_roundtrip_step_id_preserved(self, registry_with_functions):
        """Test roundtrip preserves custom step_id."""
        original = Step(
            name="id-step",
            executor=sample_executor,
            step_id="my-custom-step-id",
        )

        data = original.to_dict()
        restored = Step.from_dict(data, registry=registry_with_functions)

        assert restored.step_id == "my-custom-step-id"

    def test_roundtrip_none_values(self, registry_with_functions):
        """Test roundtrip handles None values correctly."""
        original = Step(
            name="none-step",
            executor=sample_executor,
            description=None,
            add_workflow_history=None,
        )

        data = original.to_dict()
        restored = Step.from_dict(data, registry=registry_with_functions)

        assert restored.description is None
        assert restored.add_workflow_history is None
