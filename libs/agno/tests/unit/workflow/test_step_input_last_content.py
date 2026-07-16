"""StepInput.get_last_step_content must aggregate ALL Parallel branches, not just the
last one — otherwise a step placed after a Parallel (the fan-out -> synthesize pattern)
silently loses every branch except the last."""

from agno.workflow.types import StepInput, StepOutput, StepType


def test_parallel_content_aggregates_all_branches():
    branch_a = StepOutput(step_name="branch_a", content="AAA")
    branch_b = StepOutput(step_name="branch_b", content="BBB")
    parallel = StepOutput(step_name="par", step_type=StepType.PARALLEL, content="agg", steps=[branch_a, branch_b])
    step_input = StepInput(input="x", previous_step_outputs={"par": parallel})

    content = step_input.get_last_step_content()

    assert "AAA" in content
    assert "BBB" in content


def test_non_parallel_nested_uses_last_step():
    inner = StepOutput(step_name="inner", content="INNER")
    nested = StepOutput(
        step_name="seq",
        step_type=StepType.STEPS,
        content="c",
        steps=[StepOutput(content="first"), inner],
    )
    step_input = StepInput(input="x", previous_step_outputs={"seq": nested})

    assert step_input.get_last_step_content() == "INNER"


def test_plain_step_content_unchanged():
    step_input = StepInput(input="x", previous_step_outputs={"s": StepOutput(step_name="s", content="plain")})
    assert step_input.get_last_step_content() == "plain"
