"""
Unit tests for Parallel serialization and deserialization.

Tests cover:
- to_dict(): Serialization of Parallel to dictionary
- from_dict(): Deserialization of Parallel from dictionary
- Roundtrip serialization (no data loss)
- Nested step serialization
"""

import pytest

from agno.registry import Registry
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput

# =============================================================================
# Sample executor functions for testing
# =============================================================================


def executor_a(step_input: StepInput) -> str:
    """Executor A for testing."""
    return "result_a"


def executor_b(step_input: StepInput) -> str:
    """Executor B for testing."""
    return "result_b"


def executor_c(step_input: StepInput) -> str:
    """Executor C for testing."""
    return "result_c"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry_with_functions():
    """Create a registry with sample functions registered."""
    return Registry(functions=[executor_a, executor_b, executor_c])


@pytest.fixture
def simple_steps(registry_with_functions):
    """Create simple steps for testing."""
    return [
        Step(name="step-a", executor=executor_a),
        Step(name="step-b", executor=executor_b),
    ]


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestParallelToDict:
    """Tests for Parallel.to_dict() method."""

    def test_to_dict_basic(self, simple_steps):
        """Test to_dict with basic parallel configuration."""
        parallel = Parallel(*simple_steps, name="basic-parallel", description="Basic parallel step")

        result = parallel.to_dict()

        assert result["type"] == "Parallel"
        assert result["name"] == "basic-parallel"
        assert result["description"] == "Basic parallel step"
        assert len(result["steps"]) == 2

    def test_to_dict_serializes_nested_steps(self, simple_steps):
        """Test to_dict serializes nested steps correctly."""
        parallel = Parallel(*simple_steps, name="nested-parallel")

        result = parallel.to_dict()

        assert len(result["steps"]) == 2
        assert result["steps"][0]["name"] == "step-a"
        assert result["steps"][0]["type"] == "Step"
        assert result["steps"][1]["name"] == "step-b"
        assert result["steps"][1]["type"] == "Step"

    def test_to_dict_preserves_step_details(self):
        """Test to_dict preserves all step configuration details."""
        step = Step(
            name="detailed-step",
            executor=executor_a,
            description="Detailed description",
            max_retries=5,
            skip_on_failure=True,
        )
        parallel = Parallel(step, name="detail-parallel")

        result = parallel.to_dict()

        step_data = result["steps"][0]
        assert step_data["name"] == "detailed-step"
        assert step_data["description"] == "Detailed description"
        assert step_data["max_retries"] == 5
        assert step_data["skip_on_failure"] is True

    def test_to_dict_with_none_values(self):
        """Test to_dict handles None name and description."""
        step = Step(name="simple-step", executor=executor_a)
        parallel = Parallel(step)

        result = parallel.to_dict()

        assert result["name"] is None
        assert result["description"] is None
        assert result["type"] == "Parallel"


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestParallelFromDict:
    """Tests for Parallel.from_dict() method."""

    def test_from_dict_basic(self, registry_with_functions):
        """Test from_dict creates parallel with basic config."""
        data = {
            "type": "Parallel",
            "name": "basic-parallel",
            "description": "Basic parallel step",
            "steps": [
                {
                    "type": "Step",
                    "name": "step-a",
                    "executor_ref": "executor_a",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        parallel = Parallel.from_dict(data, registry=registry_with_functions)

        assert parallel.name == "basic-parallel"
        assert parallel.description == "Basic parallel step"
        assert len(parallel.steps) == 1

    def test_from_dict_with_multiple_steps(self, registry_with_functions):
        """Test from_dict with multiple nested steps."""
        data = {
            "type": "Parallel",
            "name": "multi-parallel",
            "description": None,
            "steps": [
                {
                    "type": "Step",
                    "name": "step-a",
                    "executor_ref": "executor_a",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
                {
                    "type": "Step",
                    "name": "step-b",
                    "executor_ref": "executor_b",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        parallel = Parallel.from_dict(data, registry=registry_with_functions)

        assert len(parallel.steps) == 2
        assert parallel.steps[0].name == "step-a"
        assert parallel.steps[1].name == "step-b"

    def test_from_dict_preserves_step_configuration(self, registry_with_functions):
        """Test from_dict preserves nested step configuration."""
        data = {
            "type": "Parallel",
            "name": "config-parallel",
            "description": None,
            "steps": [
                {
                    "type": "Step",
                    "name": "configured-step",
                    "executor_ref": "executor_a",
                    "description": "Step description",
                    "max_retries": 5,
                    "skip_on_failure": True,
                    "strict_input_validation": True,
                    "num_history_runs": 10,
                },
            ],
        }

        parallel = Parallel.from_dict(data, registry=registry_with_functions)

        step = parallel.steps[0]
        assert step.name == "configured-step"
        assert step.description == "Step description"
        assert step.max_retries == 5
        assert step.skip_on_failure is True
        assert step.strict_input_validation is True
        assert step.num_history_runs == 10


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestParallelSerializationRoundtrip:
    """Tests for Parallel serialization roundtrip (to_dict -> from_dict)."""

    def test_roundtrip_basic(self, registry_with_functions):
        """Test roundtrip preserves basic parallel configuration."""
        step_a = Step(name="step-a", executor=executor_a)
        step_b = Step(name="step-b", executor=executor_b)
        original = Parallel(step_a, step_b, name="roundtrip-parallel", description="Test description")

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        # Verify no data loss
        assert restored.name == original.name
        assert restored.description == original.description
        assert len(restored.steps) == len(original.steps)

    def test_roundtrip_preserves_type_field(self, registry_with_functions):
        """Test roundtrip preserves type field for proper deserialization dispatch."""
        step = Step(name="typed-step", executor=executor_a)
        parallel = Parallel(step, name="typed-parallel")

        data = parallel.to_dict()
        assert data["type"] == "Parallel"

        restored = Parallel.from_dict(data, registry=registry_with_functions)
        assert restored.name == "typed-parallel"

    def test_roundtrip_preserves_nested_step_names(self, registry_with_functions):
        """Test roundtrip preserves all nested step names."""
        steps = [
            Step(name="first", executor=executor_a),
            Step(name="second", executor=executor_b),
            Step(name="third", executor=executor_c),
        ]
        original = Parallel(*steps, name="multi-step-parallel")

        data = original.to_dict()
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        assert len(restored.steps) == 3
        assert restored.steps[0].name == "first"
        assert restored.steps[1].name == "second"
        assert restored.steps[2].name == "third"

    def test_roundtrip_preserves_step_executors(self, registry_with_functions):
        """Test roundtrip preserves executor function references."""
        step_a = Step(name="step-a", executor=executor_a)
        step_b = Step(name="step-b", executor=executor_b)
        original = Parallel(step_a, step_b, name="executor-parallel")

        data = original.to_dict()
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        assert restored.steps[0].executor == executor_a
        assert restored.steps[1].executor == executor_b

    def test_roundtrip_preserves_step_configuration(self, registry_with_functions):
        """Test roundtrip preserves all step configuration fields."""
        step = Step(
            name="configured-step",
            executor=executor_a,
            description="Step description",
            max_retries=5,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=8,
        )
        original = Parallel(step, name="config-parallel")

        data = original.to_dict()
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        restored_step = restored.steps[0]
        assert restored_step.name == "configured-step"
        assert restored_step.description == "Step description"
        assert restored_step.max_retries == 5
        assert restored_step.skip_on_failure is True
        assert restored_step.strict_input_validation is True
        assert restored_step.add_workflow_history is True
        assert restored_step.num_history_runs == 8

    def test_roundtrip_with_none_values(self, registry_with_functions):
        """Test roundtrip handles None values correctly."""
        step = Step(name="simple-step", executor=executor_a)
        original = Parallel(step)  # name and description are None

        data = original.to_dict()
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        assert restored.name is None
        assert restored.description is None


# =============================================================================
# Nested Container Tests
# =============================================================================


class TestParallelNestedContainerSerialization:
    """Tests for Parallel with nested container steps (Loop, Steps, Condition, etc.)."""

    def test_roundtrip_with_nested_parallel(self, registry_with_functions):
        """Test roundtrip with nested Parallel inside Parallel."""
        inner_step = Step(name="inner-step", executor=executor_a)
        inner_parallel = Parallel(inner_step, name="inner-parallel")
        outer_parallel = Parallel(inner_parallel, name="outer-parallel")

        data = outer_parallel.to_dict()
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        assert restored.name == "outer-parallel"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "inner-parallel"
        assert isinstance(restored.steps[0], Parallel)

    def test_roundtrip_with_nested_steps_container(self, registry_with_functions):
        """Test roundtrip with nested Steps container inside Parallel."""
        from agno.workflow.steps import Steps

        step_a = Step(name="step-a", executor=executor_a)
        step_b = Step(name="step-b", executor=executor_b)
        steps_container = Steps(name="steps-container", steps=[step_a, step_b])
        parallel = Parallel(steps_container, name="parallel-with-steps")

        data = parallel.to_dict()
        restored = Parallel.from_dict(data, registry=registry_with_functions)

        assert restored.name == "parallel-with-steps"
        assert len(restored.steps) == 1
        assert restored.steps[0].name == "steps-container"
        assert isinstance(restored.steps[0], Steps)
        assert len(restored.steps[0].steps) == 2


# =============================================================================
# Dataclass Field Tests
# =============================================================================


class TestParallelStepsField:
    """Tests for Parallel.steps as a dataclass field with default_factory."""

    def test_no_args_gives_empty_steps(self):
        """Test that Parallel() with no args defaults to an empty steps list."""
        parallel = Parallel()
        assert parallel.steps == []
        assert parallel.name is None
        assert parallel.description is None

    def test_instances_do_not_share_steps(self):
        """Test that each Parallel instance gets its own steps list (no mutable default sharing)."""
        p1 = Parallel()
        p2 = Parallel()

        step = Step(name="only-for-p1", executor=executor_a)
        p1.steps.append(step)

        assert len(p1.steps) == 1
        assert len(p2.steps) == 0

    def test_steps_set_via_init_args(self):
        """Test that steps passed via *args are stored correctly."""
        step_a = Step(name="a", executor=executor_a)
        step_b = Step(name="b", executor=executor_b)
        parallel = Parallel(step_a, step_b)

        assert len(parallel.steps) == 2
        assert parallel.steps[0] is step_a
        assert parallel.steps[1] is step_b

    def test_steps_field_is_dataclass_field(self):
        """Test that steps is a recognized dataclass field."""
        import dataclasses

        fields = {f.name for f in dataclasses.fields(Parallel)}
        assert "steps" in fields
        assert "name" in fields
        assert "description" in fields

    def test_steps_field_default_factory(self):
        """Test that the steps field uses a default_factory (list)."""
        import dataclasses

        steps_field = next(f for f in dataclasses.fields(Parallel) if f.name == "steps")
        assert steps_field.default is dataclasses.MISSING
        assert steps_field.default_factory is list
