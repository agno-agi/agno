"""
Unit tests for Loop serialization and deserialization.

Tests cover:
- to_dict(): Serialization of Loop to dictionary
- from_dict(): Deserialization of Loop from dictionary
- Roundtrip serialization (no data loss)
- end_condition callable serialization
- Nested step serialization
"""

from typing import List

import pytest

from agno.registry import Registry
from agno.workflow.loop import Loop
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput

# =============================================================================
# Sample executor and end_condition functions for testing
# =============================================================================


def loop_executor_1(step_input: StepInput) -> str:
    """First loop executor."""
    return "result_1"


def loop_executor_2(step_input: StepInput) -> str:
    """Second loop executor."""
    return "result_2"


def simple_end_condition(results: List[StepOutput]) -> bool:
    """Simple end condition that always returns False (continue looping)."""
    return False


def count_end_condition(results: List[StepOutput]) -> bool:
    """End condition that stops after a certain count."""
    return len(results) >= 3


def content_end_condition(results: List[StepOutput]) -> bool:
    """End condition based on content."""
    if results:
        return "done" in str(results[-1].content).lower()
    return False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry_with_functions():
    """Create a registry with sample functions registered."""
    return Registry(
        functions=[
            loop_executor_1,
            loop_executor_2,
            simple_end_condition,
            count_end_condition,
            content_end_condition,
        ]
    )


@pytest.fixture
def simple_steps():
    """Create simple steps for testing."""
    return [
        Step(name="loop-step-1", executor=loop_executor_1),
        Step(name="loop-step-2", executor=loop_executor_2),
    ]


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestLoopToDict:
    """Tests for Loop.to_dict() method."""

    def test_to_dict_basic(self, simple_steps):
        """Test to_dict with basic Loop configuration."""
        loop = Loop(
            name="basic-loop",
            description="Basic loop step",
            steps=simple_steps,
            max_iterations=5,
        )

        result = loop.to_dict()

        assert result["type"] == "Loop"
        assert result["name"] == "basic-loop"
        assert result["description"] == "Basic loop step"
        assert result["max_iterations"] == 5
        assert len(result["steps"]) == 2

    def test_to_dict_serializes_end_condition(self, simple_steps):
        """Test to_dict serializes end_condition function by name."""
        loop = Loop(
            name="condition-loop",
            steps=simple_steps,
            max_iterations=10,
            end_condition=simple_end_condition,
        )

        result = loop.to_dict()

        assert result["end_condition"] == "simple_end_condition"

    def test_to_dict_with_none_end_condition(self, simple_steps):
        """Test to_dict handles None end_condition."""
        loop = Loop(
            name="no-condition-loop",
            steps=simple_steps,
            max_iterations=3,
            end_condition=None,
        )

        result = loop.to_dict()

        assert result["end_condition"] is None

    def test_to_dict_serializes_nested_steps(self, simple_steps):
        """Test to_dict serializes nested steps correctly."""
        loop = Loop(name="nested-loop", steps=simple_steps, max_iterations=3)

        result = loop.to_dict()

        assert len(result["steps"]) == 2
        assert result["steps"][0]["name"] == "loop-step-1"
        assert result["steps"][0]["type"] == "Step"
        assert result["steps"][1]["name"] == "loop-step-2"
        assert result["steps"][1]["type"] == "Step"

    def test_to_dict_preserves_step_details(self):
        """Test to_dict preserves all step configuration details."""
        step = Step(
            name="detailed-step",
            executor=loop_executor_1,
            description="Detailed description",
            max_retries=5,
            skip_on_failure=True,
        )
        loop = Loop(name="detail-loop", steps=[step], max_iterations=2)

        result = loop.to_dict()

        step_data = result["steps"][0]
        assert step_data["name"] == "detailed-step"
        assert step_data["description"] == "Detailed description"
        assert step_data["max_retries"] == 5
        assert step_data["skip_on_failure"] is True

    def test_to_dict_default_max_iterations(self, simple_steps):
        """Test to_dict includes default max_iterations."""
        loop = Loop(name="default-loop", steps=simple_steps)

        result = loop.to_dict()

        assert result["max_iterations"] == 3  # Default value


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestLoopFromDict:
    """Tests for Loop.from_dict() method."""

    def test_from_dict_basic(self, registry_with_functions):
        """Test from_dict creates Loop with basic config."""
        data = {
            "type": "Loop",
            "name": "basic-loop",
            "description": "Basic loop step",
            "max_iterations": 5,
            "end_condition": None,
            "steps": [
                {
                    "type": "Step",
                    "name": "loop-step-1",
                    "executor_ref": "loop_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        loop = Loop.from_dict(data, registry=registry_with_functions)

        assert loop.name == "basic-loop"
        assert loop.description == "Basic loop step"
        assert loop.max_iterations == 5
        assert loop.end_condition is None
        assert len(loop.steps) == 1

    def test_from_dict_restores_end_condition(self, registry_with_functions):
        """Test from_dict restores end_condition function from registry."""
        data = {
            "type": "Loop",
            "name": "condition-loop",
            "description": None,
            "max_iterations": 10,
            "end_condition": "simple_end_condition",
            "steps": [
                {
                    "type": "Step",
                    "name": "loop-step",
                    "executor_ref": "loop_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        loop = Loop.from_dict(data, registry=registry_with_functions)

        assert loop.end_condition == simple_end_condition
        assert callable(loop.end_condition)

    def test_from_dict_raises_without_registry_for_end_condition(self):
        """Test from_dict raises error when end_condition needs registry but none provided."""
        data = {
            "type": "Loop",
            "name": "condition-loop",
            "description": None,
            "max_iterations": 10,
            "end_condition": "simple_end_condition",
            "steps": [],
        }

        with pytest.raises(ValueError, match="Registry required"):
            Loop.from_dict(data, registry=None)

    def test_from_dict_raises_for_unknown_end_condition(self, registry_with_functions):
        """Test from_dict raises error for unknown end_condition function."""
        data = {
            "type": "Loop",
            "name": "unknown-condition-loop",
            "description": None,
            "max_iterations": 5,
            "end_condition": "unknown_function",
            "steps": [],
        }

        with pytest.raises(ValueError, match="not found in registry"):
            Loop.from_dict(data, registry=registry_with_functions)

    def test_from_dict_with_multiple_steps(self, registry_with_functions):
        """Test from_dict with multiple nested steps."""
        data = {
            "type": "Loop",
            "name": "multi-loop",
            "description": None,
            "max_iterations": 3,
            "end_condition": None,
            "steps": [
                {
                    "type": "Step",
                    "name": "loop-step-1",
                    "executor_ref": "loop_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
                {
                    "type": "Step",
                    "name": "loop-step-2",
                    "executor_ref": "loop_executor_2",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        loop = Loop.from_dict(data, registry=registry_with_functions)

        assert len(loop.steps) == 2
        assert loop.steps[0].name == "loop-step-1"
        assert loop.steps[1].name == "loop-step-2"


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestLoopSerializationRoundtrip:
    """Tests for Loop serialization roundtrip (to_dict -> from_dict)."""

    def test_roundtrip_basic(self, registry_with_functions):
        """Test roundtrip preserves basic Loop configuration."""
        step_1 = Step(name="step-1", executor=loop_executor_1)
        step_2 = Step(name="step-2", executor=loop_executor_2)
        original = Loop(
            name="roundtrip-loop",
            description="Test description",
            steps=[step_1, step_2],
            max_iterations=7,
        )

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Loop.from_dict(data, registry=registry_with_functions)

        # Verify no data loss
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.max_iterations == original.max_iterations
        assert len(restored.steps) == len(original.steps)

    def test_roundtrip_preserves_type_field(self, registry_with_functions):
        """Test roundtrip preserves type field for proper deserialization dispatch."""
        step = Step(name="typed-step", executor=loop_executor_1)
        loop = Loop(name="typed-loop", steps=[step], max_iterations=3)

        data = loop.to_dict()
        assert data["type"] == "Loop"

        restored = Loop.from_dict(data, registry=registry_with_functions)
        assert restored.name == "typed-loop"

    def test_roundtrip_preserves_end_condition(self, registry_with_functions):
        """Test roundtrip preserves end_condition function reference."""
        step = Step(name="condition-step", executor=loop_executor_1)
        original = Loop(
            name="condition-loop",
            steps=[step],
            max_iterations=10,
            end_condition=count_end_condition,
        )

        data = original.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert restored.end_condition == count_end_condition
        assert callable(restored.end_condition)

    def test_roundtrip_preserves_none_end_condition(self, registry_with_functions):
        """Test roundtrip preserves None end_condition."""
        step = Step(name="no-condition-step", executor=loop_executor_1)
        original = Loop(
            name="no-condition-loop",
            steps=[step],
            max_iterations=5,
            end_condition=None,
        )

        data = original.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert restored.end_condition is None

    def test_roundtrip_preserves_nested_step_names(self, registry_with_functions):
        """Test roundtrip preserves all nested step names."""
        steps = [
            Step(name="first", executor=loop_executor_1),
            Step(name="second", executor=loop_executor_2),
        ]
        original = Loop(name="multi-step-loop", steps=steps, max_iterations=3)

        data = original.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert len(restored.steps) == 2
        assert restored.steps[0].name == "first"
        assert restored.steps[1].name == "second"

    def test_roundtrip_preserves_step_executors(self, registry_with_functions):
        """Test roundtrip preserves executor function references."""
        step_1 = Step(name="step-1", executor=loop_executor_1)
        step_2 = Step(name="step-2", executor=loop_executor_2)
        original = Loop(name="executor-loop", steps=[step_1, step_2], max_iterations=3)

        data = original.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert restored.steps[0].executor == loop_executor_1
        assert restored.steps[1].executor == loop_executor_2

    def test_roundtrip_preserves_step_configuration(self, registry_with_functions):
        """Test roundtrip preserves all step configuration fields."""
        step = Step(
            name="configured-step",
            executor=loop_executor_1,
            description="Step description",
            max_retries=5,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=8,
        )
        original = Loop(name="config-loop", steps=[step], max_iterations=4)

        data = original.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        restored_step = restored.steps[0]
        assert restored_step.name == "configured-step"
        assert restored_step.description == "Step description"
        assert restored_step.max_retries == 5
        assert restored_step.skip_on_failure is True
        assert restored_step.strict_input_validation is True
        assert restored_step.add_workflow_history is True
        assert restored_step.num_history_runs == 8

    def test_roundtrip_with_different_end_conditions(self, registry_with_functions):
        """Test roundtrip with different end_condition functions."""
        for end_cond in [simple_end_condition, count_end_condition, content_end_condition]:
            step = Step(name="test-step", executor=loop_executor_1)
            original = Loop(
                name=f"loop-with-{end_cond.__name__}",
                steps=[step],
                max_iterations=5,
                end_condition=end_cond,
            )

            data = original.to_dict()
            restored = Loop.from_dict(data, registry=registry_with_functions)

            assert restored.end_condition == end_cond


# =============================================================================
# Nested Container Tests
# =============================================================================


class TestLoopNestedContainerSerialization:
    """Tests for Loop with nested container steps (Parallel, Steps, Condition, etc.)."""

    def test_roundtrip_with_nested_loop(self, registry_with_functions):
        """Test roundtrip with nested Loop inside Loop."""
        inner_step = Step(name="inner-step", executor=loop_executor_1)
        inner_loop = Loop(name="inner-loop", steps=[inner_step], max_iterations=2)
        outer_loop = Loop(name="outer-loop", steps=[inner_loop], max_iterations=3)

        data = outer_loop.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert restored.name == "outer-loop"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "inner-loop"
        assert isinstance(restored.steps[0], Loop)
        assert restored.steps[0].max_iterations == 2

    def test_roundtrip_with_nested_parallel(self, registry_with_functions):
        """Test roundtrip with nested Parallel container inside Loop."""
        from agno.workflow.parallel import Parallel

        step_1 = Step(name="step-1", executor=loop_executor_1)
        step_2 = Step(name="step-2", executor=loop_executor_2)
        parallel = Parallel(step_1, step_2, name="parallel-container")
        loop = Loop(name="loop-with-parallel", steps=[parallel], max_iterations=3)

        data = loop.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert restored.name == "loop-with-parallel"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "parallel-container"
        assert isinstance(restored.steps[0], Parallel)
        assert len(restored.steps[0].steps) == 2

    def test_roundtrip_with_nested_steps_container(self, registry_with_functions):
        """Test roundtrip with nested Steps container inside Loop."""
        from agno.workflow.steps import Steps

        step_1 = Step(name="step-1", executor=loop_executor_1)
        step_2 = Step(name="step-2", executor=loop_executor_2)
        steps_container = Steps(name="steps-container", steps=[step_1, step_2])
        loop = Loop(name="loop-with-steps", steps=[steps_container], max_iterations=3)

        data = loop.to_dict()
        restored = Loop.from_dict(data, registry=registry_with_functions)

        assert restored.name == "loop-with-steps"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "steps-container"
        assert isinstance(restored.steps[0], Steps)
        assert len(restored.steps[0].steps) == 2
