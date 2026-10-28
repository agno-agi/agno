"""Human-edited output must keep its JSON type across a serialized continuation."""

import json
from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel

from agno.db.in_memory import InMemoryDb
from agno.workflow import Step, Workflow
from agno.workflow.types import HumanReview, StepInput, StepOutput, StepRequirement


@pytest.mark.parametrize("value", [False, True, 0, 7, -3, 0.0, 2.5, "ok", "", [], [1], {}, {"a": 1}, None])
def test_edited_output_preserves_json_native_types(value: Any):
    requirement = StepRequirement(step_id="review", requires_output_review=True)
    requirement.edit(value)

    restored = StepRequirement.from_dict(json.loads(json.dumps(requirement.to_dict())))

    assert restored.confirmed is True
    assert restored.edited_output == value
    assert type(restored.edited_output) is type(value)
    assert bool(restored.edited_output) == bool(value)


def test_edited_model_still_serializes_to_json():
    class Report(BaseModel):
        approved: bool
        created_at: datetime

    requirement = StepRequirement(step_id="review", requires_output_review=True)
    requirement.edit(Report(approved=False, created_at=datetime(2026, 1, 2)))

    restored = StepRequirement.from_dict(json.loads(json.dumps(requirement.to_dict())))

    assert restored.edited_output == {"approved": False, "created_at": "2026-01-02T00:00:00"}


def test_non_json_edited_output_still_falls_back_to_string():
    value = datetime(2026, 1, 2)
    requirement = StepRequirement(step_id="review", requires_output_review=True)
    requirement.edit(value)

    restored = StepRequirement.from_dict(json.loads(json.dumps(requirement.to_dict())))

    assert restored.edited_output == str(value)


def _produce_output(step_input: StepInput) -> StepOutput:
    return StepOutput(content=True)


def _inspect_output(step_input: StepInput) -> StepOutput:
    value = step_input.previous_step_content
    return StepOutput(content={"value": value, "type": type(value).__name__, "truthy": bool(value)})


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("value", [False, 0, 0.0], ids=["bool", "int", "float"])
async def test_serialized_review_keeps_falsy_output_when_resuming(use_async: bool, value: Any):
    workflow = Workflow(
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(
                name="produce",
                executor=_produce_output,
                human_review=HumanReview(requires_output_review=True),
            ),
            Step(name="inspect", executor=_inspect_output),
        ],
    )
    paused = await workflow.arun("go") if use_async else workflow.run("go")
    assert paused.is_paused
    assert paused.step_requirements
    paused.step_requirements[0].edit(value)
    paused.step_requirements = [
        StepRequirement.from_dict(json.loads(json.dumps(requirement.to_dict())))
        for requirement in paused.step_requirements
    ]

    resumed = await workflow.acontinue_run(paused) if use_async else workflow.continue_run(paused)

    assert resumed.content == {"value": value, "type": type(value).__name__, "truthy": False}
