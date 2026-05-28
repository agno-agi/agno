"""
Unit tests for Condition serialization and deserialization.

Tests cover:
- to_dict(): Serialization of Condition to dictionary
- from_dict(): Deserialization of Condition from dictionary
- Roundtrip serialization (no data loss)
- evaluator callable serialization
- Boolean evaluator serialization
- Nested step serialization
"""

from typing import List

import pytest

from agno.registry import Registry
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput

# =============================================================================
# Sample executor and evaluator functions for testing
# =============================================================================


def condition_executor_1(step_input: StepInput) -> str:
    """First condition executor."""
    return "result_1"


def condition_executor_2(step_input: StepInput) -> str:
    """Second condition executor."""
    return "result_2"


def always_true_evaluator(step_input: StepInput) -> bool:
    """Evaluator that always returns True."""
    return True


def always_false_evaluator(step_input: StepInput) -> bool:
    """Evaluator that always returns False."""
    return False


def content_based_evaluator(step_input: StepInput) -> bool:
    """Evaluator based on input content."""
    return "proceed" in str(step_input.input).lower()


def complex_evaluator(step_input: StepInput) -> bool:
    """Complex evaluator with multiple conditions."""
    if step_input.previous_step_content:
        return "success" in str(step_input.previous_step_content).lower()
    return False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry_with_functions():
    """Create a registry with sample functions registered."""
    return Registry(
        functions=[
            condition_executor_1,
            condition_executor_2,
            always_true_evaluator,
            always_false_evaluator,
            content_based_evaluator,
            complex_evaluator,
        ]
    )


@pytest.fixture
def simple_steps():
    """Create simple steps for testing."""
    return [
        Step(name="condition-step-1", executor=condition_executor_1),
        Step(name="condition-step-2", executor=condition_executor_2),
    ]


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestConditionToDict:
    """Tests for Condition.to_dict() method."""

    def test_to_dict_basic(self, simple_steps):
        """Test to_dict with basic Condition configuration."""
        condition = Condition(
            name="basic-condition",
            description="Basic condition step",
            evaluator=always_true_evaluator,
            steps=simple_steps,
        )

        result = condition.to_dict()

        assert result["type"] == "Condition"
        assert result["name"] == "basic-condition"
        assert result["description"] == "Basic condition step"
        assert len(result["steps"]) == 2

    def test_to_dict_serializes_callable_evaluator(self, simple_steps):
        """Test to_dict serializes callable evaluator by name."""
        condition = Condition(
            name="callable-condition",
            evaluator=content_based_evaluator,
            steps=simple_steps,
        )

        result = condition.to_dict()

        assert result["evaluator"] == "content_based_evaluator"

    def test_to_dict_serializes_boolean_evaluator(self, simple_steps):
        """Test to_dict serializes boolean evaluator directly."""
        # Test with True
        condition_true = Condition(
            name="true-condition",
            evaluator=True,
            steps=simple_steps,
        )
        result_true = condition_true.to_dict()
        assert result_true["evaluator"] is True

        # Test with False
        condition_false = Condition(
            name="false-condition",
            evaluator=False,
            steps=simple_steps,
        )
        result_false = condition_false.to_dict()
        assert result_false["evaluator"] is False

    def test_to_dict_serializes_nested_steps(self, simple_steps):
        """Test to_dict serializes nested steps correctly."""
        condition = Condition(name="nested-condition", evaluator=always_true_evaluator, steps=simple_steps)

        result = condition.to_dict()

        assert len(result["steps"]) == 2
        assert result["steps"][0]["name"] == "condition-step-1"
        assert result["steps"][0]["type"] == "Step"
        assert result["steps"][1]["name"] == "condition-step-2"
        assert result["steps"][1]["type"] == "Step"

    def test_to_dict_preserves_step_details(self):
        """Test to_dict preserves all step configuration details."""
        step = Step(
            name="detailed-step",
            executor=condition_executor_1,
            description="Detailed description",
            max_retries=5,
            skip_on_failure=True,
        )
        condition = Condition(name="detail-condition", evaluator=always_true_evaluator, steps=[step])

        result = condition.to_dict()

        step_data = result["steps"][0]
        assert step_data["name"] == "detailed-step"
        assert step_data["description"] == "Detailed description"
        assert step_data["max_retries"] == 5
        assert step_data["skip_on_failure"] is True


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestConditionFromDict:
    """Tests for Condition.from_dict() method."""

    def test_from_dict_basic(self, registry_with_functions):
        """Test from_dict creates Condition with basic config."""
        data = {
            "type": "Condition",
            "name": "basic-condition",
            "description": "Basic condition step",
            "evaluator": "always_true_evaluator",
            "steps": [
                {
                    "type": "Step",
                    "name": "condition-step-1",
                    "executor_ref": "condition_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        condition = Condition.from_dict(data, registry=registry_with_functions)

        assert condition.name == "basic-condition"
        assert condition.description == "Basic condition step"
        assert condition.evaluator == always_true_evaluator
        assert len(condition.steps) == 1

    def test_from_dict_restores_callable_evaluator(self, registry_with_functions):
        """Test from_dict restores callable evaluator function from registry."""
        data = {
            "type": "Condition",
            "name": "callable-condition",
            "description": None,
            "evaluator": "content_based_evaluator",
            "steps": [
                {
                    "type": "Step",
                    "name": "step",
                    "executor_ref": "condition_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        condition = Condition.from_dict(data, registry=registry_with_functions)

        assert condition.evaluator == content_based_evaluator
        assert callable(condition.evaluator)

    def test_from_dict_restores_boolean_evaluator(self, registry_with_functions):
        """Test from_dict restores boolean evaluator directly."""
        # Test with True
        data_true = {
            "type": "Condition",
            "name": "true-condition",
            "description": None,
            "evaluator": True,
            "steps": [],
        }
        condition_true = Condition.from_dict(data_true, registry=registry_with_functions)
        assert condition_true.evaluator is True

        # Test with False
        data_false = {
            "type": "Condition",
            "name": "false-condition",
            "description": None,
            "evaluator": False,
            "steps": [],
        }
        condition_false = Condition.from_dict(data_false, registry=registry_with_functions)
        assert condition_false.evaluator is False

    def test_from_dict_raises_without_registry_for_callable_evaluator(self):
        """Test from_dict raises error when callable evaluator needs registry but none provided."""
        data = {
            "type": "Condition",
            "name": "callable-condition",
            "description": None,
            "evaluator": "always_true_evaluator",
            "steps": [],
        }

        with pytest.raises(ValueError, match="Registry required"):
            Condition.from_dict(data, registry=None)

    def test_from_dict_raises_for_unknown_evaluator(self, registry_with_functions):
        """Test from_dict raises error for unknown evaluator function."""
        data = {
            "type": "Condition",
            "name": "unknown-evaluator-condition",
            "description": None,
            "evaluator": "unknown_evaluator",
            "steps": [],
        }

        with pytest.raises(ValueError, match="not found in registry"):
            Condition.from_dict(data, registry=registry_with_functions)

    def test_from_dict_with_multiple_steps(self, registry_with_functions):
        """Test from_dict with multiple nested steps."""
        data = {
            "type": "Condition",
            "name": "multi-condition",
            "description": None,
            "evaluator": "always_true_evaluator",
            "steps": [
                {
                    "type": "Step",
                    "name": "condition-step-1",
                    "executor_ref": "condition_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
                {
                    "type": "Step",
                    "name": "condition-step-2",
                    "executor_ref": "condition_executor_2",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        condition = Condition.from_dict(data, registry=registry_with_functions)

        assert len(condition.steps) == 2
        assert condition.steps[0].name == "condition-step-1"
        assert condition.steps[1].name == "condition-step-2"


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestConditionSerializationRoundtrip:
    """Tests for Condition serialization roundtrip (to_dict -> from_dict)."""

    def test_roundtrip_basic(self, registry_with_functions):
        """Test roundtrip preserves basic Condition configuration."""
        step_1 = Step(name="step-1", executor=condition_executor_1)
        step_2 = Step(name="step-2", executor=condition_executor_2)
        original = Condition(
            name="roundtrip-condition",
            description="Test description",
            evaluator=always_true_evaluator,
            steps=[step_1, step_2],
        )

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Condition.from_dict(data, registry=registry_with_functions)

        # Verify no data loss
        assert restored.name == original.name
        assert restored.description == original.description
        assert len(restored.steps) == len(original.steps)

    def test_roundtrip_preserves_type_field(self, registry_with_functions):
        """Test roundtrip preserves type field for proper deserialization dispatch."""
        step = Step(name="typed-step", executor=condition_executor_1)
        condition = Condition(name="typed-condition", evaluator=always_true_evaluator, steps=[step])

        data = condition.to_dict()
        assert data["type"] == "Condition"

        restored = Condition.from_dict(data, registry=registry_with_functions)
        assert restored.name == "typed-condition"

    def test_roundtrip_preserves_callable_evaluator(self, registry_with_functions):
        """Test roundtrip preserves callable evaluator function reference."""
        step = Step(name="evaluator-step", executor=condition_executor_1)
        original = Condition(
            name="evaluator-condition",
            evaluator=complex_evaluator,
            steps=[step],
        )

        data = original.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert restored.evaluator == complex_evaluator
        assert callable(restored.evaluator)

    def test_roundtrip_preserves_boolean_evaluator(self, registry_with_functions):
        """Test roundtrip preserves boolean evaluator."""
        step = Step(name="bool-step", executor=condition_executor_1)

        # Test with True
        original_true = Condition(name="true-condition", evaluator=True, steps=[step])
        data_true = original_true.to_dict()
        restored_true = Condition.from_dict(data_true, registry=registry_with_functions)
        assert restored_true.evaluator is True

        # Test with False
        original_false = Condition(name="false-condition", evaluator=False, steps=[step])
        data_false = original_false.to_dict()
        restored_false = Condition.from_dict(data_false, registry=registry_with_functions)
        assert restored_false.evaluator is False

    def test_roundtrip_preserves_nested_step_names(self, registry_with_functions):
        """Test roundtrip preserves all nested step names."""
        steps = [
            Step(name="first", executor=condition_executor_1),
            Step(name="second", executor=condition_executor_2),
        ]
        original = Condition(name="multi-step-condition", evaluator=always_true_evaluator, steps=steps)

        data = original.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert len(restored.steps) == 2
        assert restored.steps[0].name == "first"
        assert restored.steps[1].name == "second"

    def test_roundtrip_preserves_step_executors(self, registry_with_functions):
        """Test roundtrip preserves executor function references."""
        step_1 = Step(name="step-1", executor=condition_executor_1)
        step_2 = Step(name="step-2", executor=condition_executor_2)
        original = Condition(name="executor-condition", evaluator=always_true_evaluator, steps=[step_1, step_2])

        data = original.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert restored.steps[0].executor == condition_executor_1
        assert restored.steps[1].executor == condition_executor_2

    def test_roundtrip_preserves_step_configuration(self, registry_with_functions):
        """Test roundtrip preserves all step configuration fields."""
        step = Step(
            name="configured-step",
            executor=condition_executor_1,
            description="Step description",
            max_retries=5,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=8,
        )
        original = Condition(name="config-condition", evaluator=always_true_evaluator, steps=[step])

        data = original.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        restored_step = restored.steps[0]
        assert restored_step.name == "configured-step"
        assert restored_step.description == "Step description"
        assert restored_step.max_retries == 5
        assert restored_step.skip_on_failure is True
        assert restored_step.strict_input_validation is True
        assert restored_step.add_workflow_history is True
        assert restored_step.num_history_runs == 8

    def test_roundtrip_with_different_evaluators(self, registry_with_functions):
        """Test roundtrip with different evaluator functions."""
        for evaluator in [always_true_evaluator, always_false_evaluator, content_based_evaluator, complex_evaluator]:
            step = Step(name="test-step", executor=condition_executor_1)
            original = Condition(
                name=f"condition-with-{evaluator.__name__}",
                evaluator=evaluator,
                steps=[step],
            )

            data = original.to_dict()
            restored = Condition.from_dict(data, registry=registry_with_functions)

            assert restored.evaluator == evaluator


# =============================================================================
# Nested Container Tests
# =============================================================================


class TestConditionNestedContainerSerialization:
    """Tests for Condition with nested container steps (Parallel, Steps, Loop, etc.)."""

    def test_roundtrip_with_nested_condition(self, registry_with_functions):
        """Test roundtrip with nested Condition inside Condition."""
        inner_step = Step(name="inner-step", executor=condition_executor_1)
        inner_condition = Condition(name="inner-condition", evaluator=always_true_evaluator, steps=[inner_step])
        outer_condition = Condition(name="outer-condition", evaluator=always_false_evaluator, steps=[inner_condition])

        data = outer_condition.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert restored.name == "outer-condition"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "inner-condition"
        assert isinstance(restored.steps[0], Condition)

    def test_roundtrip_with_nested_parallel(self, registry_with_functions):
        """Test roundtrip with nested Parallel container inside Condition."""
        from agno.workflow.parallel import Parallel

        step_1 = Step(name="step-1", executor=condition_executor_1)
        step_2 = Step(name="step-2", executor=condition_executor_2)
        parallel = Parallel(step_1, step_2, name="parallel-container")
        condition = Condition(name="condition-with-parallel", evaluator=always_true_evaluator, steps=[parallel])

        data = condition.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert restored.name == "condition-with-parallel"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "parallel-container"
        assert isinstance(restored.steps[0], Parallel)
        assert len(restored.steps[0].steps) == 2

    def test_roundtrip_with_nested_loop(self, registry_with_functions):
        """Test roundtrip with nested Loop container inside Condition."""
        from agno.workflow.loop import Loop

        step = Step(name="loop-step", executor=condition_executor_1)
        loop = Loop(name="loop-container", steps=[step], max_iterations=3)
        condition = Condition(name="condition-with-loop", evaluator=always_true_evaluator, steps=[loop])

        data = condition.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert restored.name == "condition-with-loop"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "loop-container"
        assert isinstance(restored.steps[0], Loop)
        assert restored.steps[0].max_iterations == 3

    def test_roundtrip_with_nested_steps_container(self, registry_with_functions):
        """Test roundtrip with nested Steps container inside Condition."""
        from agno.workflow.steps import Steps

        step_1 = Step(name="step-1", executor=condition_executor_1)
        step_2 = Step(name="step-2", executor=condition_executor_2)
        steps_container = Steps(name="steps-container", steps=[step_1, step_2])
        condition = Condition(name="condition-with-steps", evaluator=always_true_evaluator, steps=[steps_container])

        data = condition.to_dict()
        restored = Condition.from_dict(data, registry=registry_with_functions)

        assert restored.name == "condition-with-steps"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "steps-container"
        assert isinstance(restored.steps[0], Steps)
        assert len(restored.steps[0].steps) == 2

    def test_roundtrip_with_nested_router(self, registry_with_functions):
        """Test roundtrip with nested Router container inside Condition."""
        from agno.workflow.router import Router

        # Add a selector function to the registry
        def test_selector(step_input: StepInput) -> List[Step]:
            return []

        # Create new registry with selector
        registry = Registry(
            functions=[
                condition_executor_1,
                condition_executor_2,
                always_true_evaluator,
                test_selector,
            ]
        )

        choice = Step(name="router-choice", executor=condition_executor_1)
        router = Router(name="router-container", selector=test_selector, choices=[choice])
        condition = Condition(name="condition-with-router", evaluator=always_true_evaluator, steps=[router])

        data = condition.to_dict()
        restored = Condition.from_dict(data, registry=registry)

        assert restored.name == "condition-with-router"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "router-container"
        assert isinstance(restored.steps[0], Router)
