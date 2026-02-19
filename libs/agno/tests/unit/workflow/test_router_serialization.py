"""
Unit tests for Router serialization and deserialization.

Tests cover:
- to_dict(): Serialization of Router to dictionary
- from_dict(): Deserialization of Router from dictionary
- Roundtrip serialization (no data loss)
- selector callable serialization
- Nested choice serialization
"""

from typing import List

import pytest

from agno.registry import Registry
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput

# =============================================================================
# Sample executor and selector functions for testing
# =============================================================================


def router_executor_1(step_input: StepInput) -> str:
    """First router executor."""
    return "result_1"


def router_executor_2(step_input: StepInput) -> str:
    """Second router executor."""
    return "result_2"


def router_executor_3(step_input: StepInput) -> str:
    """Third router executor."""
    return "result_3"


def first_choice_selector(step_input: StepInput) -> List[Step]:
    """Selector that returns the first choice."""
    return []


def content_based_selector(step_input: StepInput) -> List[Step]:
    """Selector based on input content."""
    return []


def multi_choice_selector(step_input: StepInput) -> List[Step]:
    """Selector that returns multiple choices."""
    return []


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry_with_functions():
    """Create a registry with sample functions registered."""
    return Registry(
        functions=[
            router_executor_1,
            router_executor_2,
            router_executor_3,
            first_choice_selector,
            content_based_selector,
            multi_choice_selector,
        ]
    )


@pytest.fixture
def simple_choices():
    """Create simple step choices for testing."""
    return [
        Step(name="choice-1", executor=router_executor_1),
        Step(name="choice-2", executor=router_executor_2),
    ]


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestRouterToDict:
    """Tests for Router.to_dict() method."""

    def test_to_dict_basic(self, simple_choices):
        """Test to_dict with basic Router configuration."""
        router = Router(
            name="basic-router",
            description="Basic router step",
            selector=first_choice_selector,
            choices=simple_choices,
        )

        result = router.to_dict()

        assert result["type"] == "Router"
        assert result["name"] == "basic-router"
        assert result["description"] == "Basic router step"
        assert len(result["choices"]) == 2

    def test_to_dict_serializes_selector(self, simple_choices):
        """Test to_dict serializes selector function by name."""
        router = Router(
            name="selector-router",
            selector=content_based_selector,
            choices=simple_choices,
        )

        result = router.to_dict()

        assert result["selector"] == "content_based_selector"

    def test_to_dict_serializes_choices(self, simple_choices):
        """Test to_dict serializes choice steps correctly."""
        router = Router(
            name="choices-router",
            selector=first_choice_selector,
            choices=simple_choices,
        )

        result = router.to_dict()

        assert len(result["choices"]) == 2
        assert result["choices"][0]["name"] == "choice-1"
        assert result["choices"][0]["type"] == "Step"
        assert result["choices"][1]["name"] == "choice-2"
        assert result["choices"][1]["type"] == "Step"

    def test_to_dict_preserves_choice_details(self):
        """Test to_dict preserves all choice configuration details."""
        choice = Step(
            name="detailed-choice",
            executor=router_executor_1,
            description="Detailed description",
            max_retries=5,
            skip_on_failure=True,
        )
        router = Router(name="detail-router", selector=first_choice_selector, choices=[choice])

        result = router.to_dict()

        choice_data = result["choices"][0]
        assert choice_data["name"] == "detailed-choice"
        assert choice_data["description"] == "Detailed description"
        assert choice_data["max_retries"] == 5
        assert choice_data["skip_on_failure"] is True


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestRouterFromDict:
    """Tests for Router.from_dict() method."""

    def test_from_dict_basic(self, registry_with_functions):
        """Test from_dict creates Router with basic config."""
        data = {
            "type": "Router",
            "name": "basic-router",
            "description": "Basic router step",
            "selector": "first_choice_selector",
            "choices": [
                {
                    "type": "Step",
                    "name": "choice-1",
                    "executor_ref": "router_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        router = Router.from_dict(data, registry=registry_with_functions)

        assert router.name == "basic-router"
        assert router.description == "Basic router step"
        assert router.selector == first_choice_selector
        assert len(router.choices) == 1

    def test_from_dict_restores_selector(self, registry_with_functions):
        """Test from_dict restores selector function from registry."""
        data = {
            "type": "Router",
            "name": "selector-router",
            "description": None,
            "selector": "content_based_selector",
            "choices": [
                {
                    "type": "Step",
                    "name": "choice",
                    "executor_ref": "router_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        router = Router.from_dict(data, registry=registry_with_functions)

        assert router.selector == content_based_selector
        assert callable(router.selector)

    def test_from_dict_raises_without_registry_for_selector(self):
        """Test from_dict raises error when selector needs registry but none provided."""
        data = {
            "type": "Router",
            "name": "selector-router",
            "description": None,
            "selector": "first_choice_selector",
            "choices": [],
        }

        with pytest.raises(ValueError, match="Registry required"):
            Router.from_dict(data, registry=None)

    def test_from_dict_raises_for_unknown_selector(self, registry_with_functions):
        """Test from_dict raises error for unknown selector function."""
        data = {
            "type": "Router",
            "name": "unknown-selector-router",
            "description": None,
            "selector": "unknown_selector",
            "choices": [],
        }

        with pytest.raises(ValueError, match="not found in registry"):
            Router.from_dict(data, registry=registry_with_functions)

    def test_from_dict_raises_without_selector(self, registry_with_functions):
        """Test from_dict raises error when no selector provided."""
        data = {
            "type": "Router",
            "name": "no-selector-router",
            "description": None,
            "selector": None,
            "choices": [],
        }

        with pytest.raises(ValueError, match="requires a selector"):
            Router.from_dict(data, registry=registry_with_functions)

    def test_from_dict_with_multiple_choices(self, registry_with_functions):
        """Test from_dict with multiple choice steps."""
        data = {
            "type": "Router",
            "name": "multi-router",
            "description": None,
            "selector": "multi_choice_selector",
            "choices": [
                {
                    "type": "Step",
                    "name": "choice-1",
                    "executor_ref": "router_executor_1",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
                {
                    "type": "Step",
                    "name": "choice-2",
                    "executor_ref": "router_executor_2",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
                {
                    "type": "Step",
                    "name": "choice-3",
                    "executor_ref": "router_executor_3",
                    "max_retries": 3,
                    "skip_on_failure": False,
                    "strict_input_validation": False,
                },
            ],
        }

        router = Router.from_dict(data, registry=registry_with_functions)

        assert len(router.choices) == 3
        assert router.choices[0].name == "choice-1"
        assert router.choices[1].name == "choice-2"
        assert router.choices[2].name == "choice-3"


# =============================================================================
# Roundtrip Tests
# =============================================================================


class TestRouterSerializationRoundtrip:
    """Tests for Router serialization roundtrip (to_dict -> from_dict)."""

    def test_roundtrip_basic(self, registry_with_functions):
        """Test roundtrip preserves basic Router configuration."""
        choice_1 = Step(name="choice-1", executor=router_executor_1)
        choice_2 = Step(name="choice-2", executor=router_executor_2)
        original = Router(
            name="roundtrip-router",
            description="Test description",
            selector=first_choice_selector,
            choices=[choice_1, choice_2],
        )

        # Serialize
        data = original.to_dict()

        # Deserialize
        restored = Router.from_dict(data, registry=registry_with_functions)

        # Verify no data loss
        assert restored.name == original.name
        assert restored.description == original.description
        assert len(restored.choices) == len(original.choices)

    def test_roundtrip_preserves_type_field(self, registry_with_functions):
        """Test roundtrip preserves type field for proper deserialization dispatch."""
        choice = Step(name="typed-choice", executor=router_executor_1)
        router = Router(name="typed-router", selector=first_choice_selector, choices=[choice])

        data = router.to_dict()
        assert data["type"] == "Router"

        restored = Router.from_dict(data, registry=registry_with_functions)
        assert restored.name == "typed-router"

    def test_roundtrip_preserves_selector(self, registry_with_functions):
        """Test roundtrip preserves selector function reference."""
        choice = Step(name="selector-choice", executor=router_executor_1)
        original = Router(
            name="selector-router",
            selector=content_based_selector,
            choices=[choice],
        )

        data = original.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert restored.selector == content_based_selector
        assert callable(restored.selector)

    def test_roundtrip_preserves_choice_names(self, registry_with_functions):
        """Test roundtrip preserves all choice step names."""
        choices = [
            Step(name="first", executor=router_executor_1),
            Step(name="second", executor=router_executor_2),
            Step(name="third", executor=router_executor_3),
        ]
        original = Router(name="multi-choice-router", selector=multi_choice_selector, choices=choices)

        data = original.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert len(restored.choices) == 3
        assert restored.choices[0].name == "first"
        assert restored.choices[1].name == "second"
        assert restored.choices[2].name == "third"

    def test_roundtrip_preserves_choice_executors(self, registry_with_functions):
        """Test roundtrip preserves executor function references in choices."""
        choice_1 = Step(name="choice-1", executor=router_executor_1)
        choice_2 = Step(name="choice-2", executor=router_executor_2)
        original = Router(name="executor-router", selector=first_choice_selector, choices=[choice_1, choice_2])

        data = original.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert restored.choices[0].executor == router_executor_1
        assert restored.choices[1].executor == router_executor_2

    def test_roundtrip_preserves_choice_configuration(self, registry_with_functions):
        """Test roundtrip preserves all choice configuration fields."""
        choice = Step(
            name="configured-choice",
            executor=router_executor_1,
            description="Choice description",
            max_retries=5,
            skip_on_failure=True,
            strict_input_validation=True,
            add_workflow_history=True,
            num_history_runs=8,
        )
        original = Router(name="config-router", selector=first_choice_selector, choices=[choice])

        data = original.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        restored_choice = restored.choices[0]
        assert restored_choice.name == "configured-choice"
        assert restored_choice.description == "Choice description"
        assert restored_choice.max_retries == 5
        assert restored_choice.skip_on_failure is True
        assert restored_choice.strict_input_validation is True
        assert restored_choice.add_workflow_history is True
        assert restored_choice.num_history_runs == 8

    def test_roundtrip_with_different_selectors(self, registry_with_functions):
        """Test roundtrip with different selector functions."""
        for selector in [first_choice_selector, content_based_selector, multi_choice_selector]:
            choice = Step(name="test-choice", executor=router_executor_1)
            original = Router(
                name=f"router-with-{selector.__name__}",
                selector=selector,
                choices=[choice],
            )

            data = original.to_dict()
            restored = Router.from_dict(data, registry=registry_with_functions)

            assert restored.selector == selector


# =============================================================================
# Nested Container Tests
# =============================================================================


class TestRouterNestedContainerSerialization:
    """Tests for Router with nested container choices (Parallel, Steps, Loop, etc.)."""

    def test_roundtrip_with_nested_router(self, registry_with_functions):
        """Test roundtrip with nested Router inside Router."""
        inner_choice = Step(name="inner-choice", executor=router_executor_1)
        inner_router = Router(name="inner-router", selector=first_choice_selector, choices=[inner_choice])
        outer_router = Router(name="outer-router", selector=content_based_selector, choices=[inner_router])

        data = outer_router.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert restored.name == "outer-router"
        assert len(restored.choices) == 1
        assert restored.choices[0].name == "inner-router"
        assert isinstance(restored.choices[0], Router)

    def test_roundtrip_with_nested_parallel(self, registry_with_functions):
        """Test roundtrip with nested Parallel container inside Router."""
        from agno.workflow.parallel import Parallel

        step_1 = Step(name="step-1", executor=router_executor_1)
        step_2 = Step(name="step-2", executor=router_executor_2)
        parallel = Parallel(step_1, step_2, name="parallel-choice")
        router = Router(name="router-with-parallel", selector=first_choice_selector, choices=[parallel])

        data = router.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert restored.name == "router-with-parallel"
        assert len(restored.choices) == 1
        assert restored.choices[0].name == "parallel-choice"
        assert isinstance(restored.choices[0], Parallel)
        assert len(restored.choices[0].steps) == 2

    def test_roundtrip_with_nested_loop(self, registry_with_functions):
        """Test roundtrip with nested Loop container inside Router."""
        from agno.workflow.loop import Loop

        step = Step(name="loop-step", executor=router_executor_1)
        loop = Loop(name="loop-choice", steps=[step], max_iterations=3)
        router = Router(name="router-with-loop", selector=first_choice_selector, choices=[loop])

        data = router.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert restored.name == "router-with-loop"
        assert len(restored.choices) == 1
        assert restored.choices[0].name == "loop-choice"
        assert isinstance(restored.choices[0], Loop)
        assert restored.choices[0].max_iterations == 3

    def test_roundtrip_with_nested_steps_container(self, registry_with_functions):
        """Test roundtrip with nested Steps container inside Router."""
        from agno.workflow.steps import Steps

        step_1 = Step(name="step-1", executor=router_executor_1)
        step_2 = Step(name="step-2", executor=router_executor_2)
        steps_container = Steps(name="steps-choice", steps=[step_1, step_2])
        router = Router(name="router-with-steps", selector=first_choice_selector, choices=[steps_container])

        data = router.to_dict()
        restored = Router.from_dict(data, registry=registry_with_functions)

        assert restored.name == "router-with-steps"
        assert len(restored.choices) == 1
        assert restored.choices[0].name == "steps-choice"
        assert isinstance(restored.choices[0], Steps)
        assert len(restored.choices[0].steps) == 2
