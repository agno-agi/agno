"""The native structured-input boundary must honor Literal choices."""

from typing import List, Literal, TypedDict, Union

import pytest

from agno.utils.agent import validate_input


@pytest.mark.parametrize(
    "annotation,value",
    [
        (Literal["safe", "fast"], "typo"),
        (Literal[False], 0),
        (Literal[0], False),
        (Literal["safe"], b"safe"),
        (List[Literal["safe", "fast"]], ["safe", "typo"]),
        (Union[Literal["safe"], int], "typo"),
    ],
)
def test_literal_input_rejects_values_outside_declared_choices(annotation, value):
    schema = TypedDict("LiteralInput", {"value": annotation})
    with pytest.raises(ValueError, match="value"):
        validate_input({"value": value}, schema)


@pytest.mark.parametrize(
    "annotation,value",
    [
        (Literal["safe", "fast"], "safe"),
        (Literal[False], False),
        (Literal[0], 0),
        (Literal[None], None),
        (List[Literal["safe", "fast"]], ["safe", "fast"]),
        (Union[Literal["safe"], int], 3),
    ],
)
def test_literal_input_accepts_declared_choices(annotation, value):
    schema = TypedDict("LiteralInput", {"value": annotation})
    payload = {"value": value}
    assert validate_input(payload, schema) == payload


def test_literal_json_input_uses_same_validation():
    class ModeInput(TypedDict):
        mode: Literal["safe", "fast"]

    with pytest.raises(ValueError, match="mode"):
        validate_input('{"mode": "typo"}', ModeInput)
    assert validate_input('{"mode": "safe"}', ModeInput) == {"mode": "safe"}


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("valid", [False, True])
async def test_workflow_rejects_invalid_literal_before_native_step(asynchronous, valid):
    from agno.run.cancel import cleanup_run
    from agno.workflow.step import Step
    from agno.workflow.types import StepOutput
    from agno.workflow.workflow import Workflow

    class ModeInput(TypedDict):
        mode: Literal["safe", "fast"]

    calls = []

    def execute(step_input):
        calls.append(step_input.input["mode"])
        return StepOutput(content="Native execution")

    async def async_execute(step_input):
        return execute(step_input)

    workflow = Workflow(
        name="Literal input",
        steps=[Step(name="native", executor=async_execute if asynchronous else execute)],
        input_schema=ModeInput,
        telemetry=False,
    )
    run_id = f"literal-{asynchronous}-{valid}"
    payload = {"mode": "safe" if valid else "typo"}
    try:
        if valid:
            result = (
                await workflow.arun(payload, run_id=run_id) if asynchronous else workflow.run(payload, run_id=run_id)
            )
            assert result.content == "Native execution"
            assert calls == ["safe"]
        else:
            with pytest.raises(ValueError, match="mode"):
                if asynchronous:
                    await workflow.arun(payload, run_id=run_id)
                else:
                    workflow.run(payload, run_id=run_id)
            assert calls == []
    finally:
        cleanup_run(run_id)
