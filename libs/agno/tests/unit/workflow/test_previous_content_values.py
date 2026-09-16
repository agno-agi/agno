import pytest

from agno.workflow.types import StepInput, StepOutput


@pytest.mark.parametrize("content", [0, 0.0, False, [], {}, "", "result"])
def test_previous_content_preserves_non_none_values(content):
    step_input = StepInput(previous_step_outputs={"result": StepOutput(content=content)})

    assert step_input.get_all_previous_content() == f"=== result ===\n{content}"


def test_previous_content_skips_none_and_preserves_order():
    step_input = StepInput(
        previous_step_outputs={
            "count": StepOutput(content=0),
            "missing": StepOutput(content=None),
            "approved": StepOutput(content=False),
        }
    )

    assert step_input.get_all_previous_content() == "=== count ===\n0\n\n=== approved ===\nFalse"


@pytest.mark.parametrize("outputs", [None, {}, {"missing": StepOutput(content=None)}])
def test_previous_content_without_content(outputs):
    assert StepInput(previous_step_outputs=outputs).get_all_previous_content() == ""
