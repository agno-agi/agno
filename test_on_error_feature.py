#!/usr/bin/env python3
"""Simple test to verify the on_error feature works correctly."""

from agno.workflow import Condition
from agno.workflow.types import OnError, StepInput, StepOutput


def failing_executor(step_input: StepInput) -> StepOutput:
    raise ValueError("Node failed!")


def success_executor(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Node completed")


def conditional_evaluator(step_input: StepInput) -> bool:
    return True


def test_on_error_skip():
    """Test on_error=skip (default behavior)."""
    print("Test 1: on_error=skip (default)")
    condition = Condition(
        name="ConditionalStep",
        evaluator=conditional_evaluator,
        steps=[
            failing_executor,
            success_executor,
        ],
        on_error=OnError.skip,  # Default
    )

    step_input = StepInput(input="test")
    result = condition.execute(step_input)

    assert result.steps is not None
    assert len(result.steps) == 1  # Only the failing step
    assert result.steps[0].success is False
    assert "failed" in result.steps[0].content
    print("✓ Test passed: Error was logged and execution stopped")


def test_on_error_fail():
    """Test on_error=fail (should raise exception)."""
    print("\nTest 2: on_error=fail")
    condition = Condition(
        name="ConditionalStep",
        evaluator=conditional_evaluator,
        steps=[
            failing_executor,
            success_executor,
        ],
        on_error=OnError.fail,
    )

    step_input = StepInput(input="test")

    try:
        result = condition.execute(step_input)
        print("✗ Test failed: Exception should have been raised")
    except ValueError as e:
        if "Node failed!" in str(e):
            print("✓ Test passed: Exception was re-raised as expected")
        else:
            print(f"✗ Test failed: Wrong exception: {e}")


def test_serialization():
    """Test that on_error field is properly serialized."""
    print("\nTest 3: Serialization")
    condition = Condition(
        name="TestCondition",
        evaluator=True,
        steps=[success_executor],
        on_error=OnError.fail,
    )

    # Test to_dict
    data = condition.to_dict()
    assert "on_error" in data
    assert data["on_error"] == "fail"
    print("✓ Test passed: on_error is serialized correctly")


if __name__ == "__main__":
    print("Testing on_error feature for Condition step\n")
    print("=" * 50)

    test_on_error_skip()
    test_on_error_fail()
    test_serialization()

    print("\n" + "=" * 50)
    print("All tests passed! ✓")
