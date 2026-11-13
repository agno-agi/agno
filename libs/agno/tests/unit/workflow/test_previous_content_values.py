"""Unit tests for previous step content that is falsy but not empty (0, False, empty containers).

Content that is None or blank text is still skipped.
"""

import pytest

from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, StepType


def summarize(step_input: StepInput) -> StepOutput:
    return StepOutput(content="")


@pytest.mark.parametrize("content", [0, 0.0, False, [], {}])
def test_previous_content_preserves_falsy_values(content):
    """get_all_previous_content keeps a step whose content is falsy but not empty."""
    step_input = StepInput(previous_step_outputs={"result": StepOutput(content=content)})

    assert step_input.get_all_previous_content() == f"=== result ===\n{content}"


def test_previous_content_skips_none_and_blank_text_and_preserves_order():
    """None and blank text are skipped, and the remaining steps keep their order."""
    step_input = StepInput(
        previous_step_outputs={
            "count": StepOutput(content=0),
            "missing": StepOutput(content=None),
            "blank": StepOutput(content="   "),
            "approved": StepOutput(content=False),
        }
    )

    assert step_input.get_all_previous_content() == "=== count ===\n0\n\n=== approved ===\nFalse"


def test_parallel_step_content_preserves_falsy_values():
    """get_step_content on a Parallel step keeps falsy sub-step content and skips blank text."""
    parallel_output = StepOutput(
        step_name="parallel",
        step_type=StepType.PARALLEL,
        steps=[
            StepOutput(step_name="count", content=0),
            StepOutput(step_name="approved", content=False),
            StepOutput(step_name="blank", content="   "),
        ],
    )
    step_input = StepInput(previous_step_outputs={"parallel": parallel_output})

    assert step_input.get_step_content("parallel") == {"count": "0", "approved": "False"}


def test_parallel_nested_step_content_preserves_falsy_values():
    """get_step_content on a Parallel keeps falsy content from steps nested inside a sub-step such as a Condition."""
    parallel_output = StepOutput(
        step_name="parallel",
        step_type=StepType.PARALLEL,
        steps=[
            StepOutput(
                step_name="condition",
                step_type=StepType.CONDITION,
                content="Condition completed",
                steps=[StepOutput(step_name="count", content=0), StepOutput(step_name="blank", content="   ")],
            ),
            StepOutput(step_name="label", content="ok"),
        ],
    )
    step_input = StepInput(previous_step_outputs={"parallel": parallel_output})

    assert step_input.get_step_content("parallel") == {"count": "0", "label": "ok"}


def test_parallel_aggregated_content_preserves_falsy_values():
    """Parallel aggregated content shows falsy content instead of *(No content)*."""
    parallel = Parallel(name="parallel")

    content = parallel._build_aggregated_content(
        [StepOutput(step_name="count", content=0), StepOutput(step_name="approved", content=False)]
    )

    assert "count\n0\n" in content
    assert "approved\nFalse" in content
    assert "*(No content)*" not in content


def test_next_step_input_after_parallel_preserves_falsy_values():
    """The input built for the step after a Parallel keeps falsy sub-step content and skips blank text."""
    step = Step(name="summary", executor=summarize)
    parallel_output = StepOutput(
        step_name="parallel",
        step_type=StepType.PARALLEL,
        content="aggregated",
        steps=[
            StepOutput(step_name="count", content=0),
            StepOutput(step_name="approved", content=False),
            StepOutput(step_name="blank", content="   "),
        ],
    )

    assert step._get_deepest_content_from_step_output(parallel_output) == "=== count ===\n0\n\n=== approved ===\nFalse"
