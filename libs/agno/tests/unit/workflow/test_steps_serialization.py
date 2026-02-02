"""
Unit tests for Steps serialization and deserialization.

Tests cover:
- to_dict(): Serialization of Steps to dictionary
- from_dict(): Deserialization of Steps from dictionary
- Roundtrip serialization (no data loss)
- Nested step serialization
"""

import pytest

from agno.registry import Registry
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput

# =============================================================================
# Sample executor functions for testing
# =============================================================================


def step_executor_1(step_input: StepInput) -> str:
    """First step executor."""
    return "result_1"


def step_executor_2(step_input: StepInput) -> str:
    """Second step executor."""
    return "result_2"


def step_executor_3(step_input: StepInput) -> str:
    """Third step executor."""
    return "result_3"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry_with_functions():
    """Create a registry with sample functions registered."""
    return Registry(functions=[step_executor_1, step_executor_2, step_executor_3])


@pytest.fixture
def simple_steps():
    """Create simple steps for testing."""
    return [
        Step(name="step-1", executor=step_executor_1),
        Step(name="step-2", executor=step_executor_2),
    ]


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestStepsToDict:
    """Tests for Steps.to_dict() method."""

    def test_to_dict_basic(self, simple_steps):
        """Test to_dict with basic Steps configuration."""
        steps = Steps(name="basic-steps", description="Basic steps container", steps=simple_steps)

        result = steps.to_dict()

        assert result["type"] == "Steps"
        assert result["name"] == "basic-steps"
        assert result["description"] == "Basic steps container"
        assert len(result["steps"]) == 2

    def test_to_dict_serializes_nested_steps(self, simple_steps):
        """Test to_dict serializes nested steps correctly."""
        steps = Steps(name="nested-steps", steps=simple_steps)

        result = steps.to_dict()

        assert len(result["steps"]) == 2
        assert result["steps"][0]["name"] == "step-1"
        assert result["steps"][0]["type"] == "Step"
        assert result["steps"][1]["name"] == "step-2"
        assert result["steps"][1]["type"] == "Step"

    def test_to_dict_preserves_step_details(self):
        """Test to_dict preserves all step configuration details."""
        step = Step(
            name="detailed-step",
            executor=step_executor_1,
            description="Detailed description",
            max_retries=5,
            skip_on_failure=True,
        )
        steps = Steps(name="detail-steps", steps=[step])

        result = steps.to_dict()

        step_data = result["steps"][0]
        assert step_data["name"] == "detailed-step"
        assert step_data["description"] == "Detailed description"
        assert step_data["max_retries"] == 5
        assert step_data["skip_on_failure"] is True

    def test_to_dict_empty_steps(self):
        """Test to_dict with empty steps list."""
        steps = Steps(name="empty-steps", steps=[])

        result = steps.to_dict()

        assert result["type"] == "Steps"
        assert result["name"] == "empty-steps"
        assert result["steps"] == []


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestStepsFromDict:
    """Tests for Steps.from_dict() method."""

    def test_from_dict_basic(self, registry_with_functions):
        """Test from_dict creates Steps with basic config."""
        data = {
            "type": "Steps",
            "name": "basic-steps",
            "description": "Basic steps container",
            "steps": [
                {
                    "type": "Step",
                    "name": "step-1",
                    "executor_ref": "step_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        steps = Steps.from_dict(data, registry=registry_with_functions)

        assert steps.name == "basic-steps"
        assert steps.description == "Basic steps container"
        assert len(steps.steps) == 1

    def test_from_dict_with_multiple_steps(self, registry_with_functions):
        """Test from_dict with multiple nested steps."""
        data = {
            "type": "Steps",
            "name": "multi-steps",
            "description": None,
            "steps": [
                {
                    "type": "Step",
                    "name": "step-1",
                    "executor_ref": "step_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
                {
                    "type": "Step",
                    "name": "step-2",
                    "executor_ref": "step_executor_2",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        steps = Steps.from_dict(data, registry=registry_with_functions)

        assert len(steps.steps) == 2
        assert steps.steps[0].name == "step-1"
        assert steps.steps[1].name == "step-2"

    def test_from_dict_preserves_step_configuration(self, registry_with_functions):
        """Test from_dict preserves nested step configuration."""
        data = {
            "type": "Steps",
            "name": "config-steps",
            "description": None,
            "steps": [
                {
                    "type": "Step",
                    "name": "configured-step",
                    "executor_ref": "step_executor_1",
                    "description": "Step description",
                    "max_retries": 5,
                    "skip_on_failure": True,
                    "strict_input_validation": True,
                    "num_history_runs": 10,
                },
            ],
        }

        steps = Steps.from_dict(data, registry=registry_with_functions)

        step = steps.steps[0]
        assert step.name == "configured-step"
        assert step.description == "Step description"
        assert step.max_retries == 5
        assert step.skip_on_failure is True
        assert step.strict_input_validation is True
        assert step.num_history_runs == 10


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestStepsSerializationRoundtrip:
    """Tests for Steps serialization roundtrip (to_dict -> from_dict)."""

    def test_roundtrip_basic(self, registry_with_functions):
        """Test roundtrip preserves basic Steps configuration."""
        step_1 = Step(name="step-1", executor=step_executor_1)
        step_2 = Step(name="step-2", executor=step_executor_2)
        original = Steps(name="roundtrip-steps", description="Test description", steps=[step_1, step_2])

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Steps.from_dict(data, registry=registry_with_functions)

        # Verify no data loss
        assert restored.name == original.name
        assert restored.description == original.description
        assert len(restored.steps) == len(original.steps)

    def test_roundtrip_preserves_type_field(self, registry_with_functions):
        """Test roundtrip preserves type field for proper deserialization dispatch."""
        step = Step(name="typed-step", executor=step_executor_1)
        steps = Steps(name="typed-steps", steps=[step])

        data = steps.to_dict()
        assert data["type"] == "Steps"

        restored = Steps.from_dict(data, registry=registry_with_functions)
        assert restored.name == "typed-steps"

    def test_roundtrip_preserves_nested_step_names(self, registry_with_functions):
        """Test roundtrip preserves all nested step names."""
        step_list = [
            Step(name="first", executor=step_executor_1),
            Step(name="second", executor=step_executor_2),
            Step(name="third", executor=step_executor_3),
        ]
        original = Steps(name="multi-step-steps", steps=step_list)

        data = original.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        assert len(restored.steps) == 3
        assert restored.steps[0].name == "first"
        assert restored.steps[1].name == "second"
        assert restored.steps[2].name == "third"

    def test_roundtrip_preserves_step_executors(self, registry_with_functions):
        """Test roundtrip preserves executor function references."""
        step_1 = Step(name="step-1", executor=step_executor_1)
        step_2 = Step(name="step-2", executor=step_executor_2)
        original = Steps(name="executor-steps", steps=[step_1, step_2])

        data = original.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        assert restored.steps[0].executor == step_executor_1
        assert restored.steps[1].executor == step_executor_2

    def test_roundtrip_preserves_step_configuration(self, registry_with_functions):
        """Test roundtrip preserves all step configuration fields."""
        step = Step(
            name="configured-step",
            executor=step_executor_1,
            description="Step description",
            max_retries=5,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=8,
        )
        original = Steps(name="config-steps", steps=[step])

        data = original.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        restored_step = restored.steps[0]
        assert restored_step.name == "configured-step"
        assert restored_step.description == "Step description"
        assert restored_step.max_retries == 5
        assert restored_step.skip_on_failure is True
        assert restored_step.strict_input_validation is True
        assert restored_step.add_workflow_history is True
        assert restored_step.num_history_runs == 8

    def test_roundtrip_empty_steps(self, registry_with_functions):
        """Test roundtrip with empty steps list."""
        original = Steps(name="empty-steps", steps=[])

        data = original.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        assert restored.name == "empty-steps"
        assert restored.steps == []


# =============================================================================
# Nested Container Tests
# =============================================================================


class TestStepsNestedContainerSerialization:
    """Tests for Steps with nested container steps (Loop, Parallel, Condition, etc.)."""

    def test_roundtrip_with_nested_steps(self, registry_with_functions):
        """Test roundtrip with nested Steps inside Steps."""
        inner_step = Step(name="inner-step", executor=step_executor_1)
        inner_steps = Steps(name="inner-steps", steps=[inner_step])
        outer_steps = Steps(name="outer-steps", steps=[inner_steps])

        data = outer_steps.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        assert restored.name == "outer-steps"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "inner-steps"
        assert isinstance(restored.steps[0], Steps)

    def test_roundtrip_with_nested_parallel(self, registry_with_functions):
        """Test roundtrip with nested Parallel container inside Steps."""
        from agno.workflow.parallel import Parallel

        step_1 = Step(name="step-1", executor=step_executor_1)
        step_2 = Step(name="step-2", executor=step_executor_2)
        parallel = Parallel(step_1, step_2, name="parallel-container")
        steps = Steps(name="steps-with-parallel", steps=[parallel])

        data = steps.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        assert restored.name == "steps-with-parallel"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "parallel-container"
        assert isinstance(restored.steps[0], Parallel)
        assert len(restored.steps[0].steps) == 2

    def test_roundtrip_mixed_step_types(self, registry_with_functions):
        """Test roundtrip with mixed step types (Step, Parallel, nested Steps)."""
        from agno.workflow.parallel import Parallel

        step_1 = Step(name="regular-step", executor=step_executor_1)
        parallel_steps = Parallel(
            Step(name="parallel-step-1", executor=step_executor_2),
            Step(name="parallel-step-2", executor=step_executor_3),
            name="parallel-block",
        )
        nested_steps = Steps(name="nested-steps", steps=[Step(name="nested-inner", executor=step_executor_1)])

        original = Steps(name="mixed-steps", steps=[step_1, parallel_steps, nested_steps])

        data = original.to_dict()
        restored = Steps.from_dict(data, registry=registry_with_functions)

        assert len(restored.steps) == 3
        assert isinstance(restored.steps[0], Step)
        assert restored.steps[0].name == "regular-step"
        assert isinstance(restored.steps[1], Parallel)
        assert restored.steps[1].name == "parallel-block"
        assert isinstance(restored.steps[2], Steps)
        assert restored.steps[2].name == "nested-steps"
