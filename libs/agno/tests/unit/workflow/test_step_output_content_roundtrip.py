"""Step content keeps its JSON-native type across a save and reload.

``StepOutput.to_dict()`` stringified every non-None value that was not a dict,
list or Pydantic model, so a step that returned ``0`` or ``False`` came back
from the database as ``"0"`` or ``"False"`` -- both truthy. A later step reading
that content through ``previous_step_outputs`` (after a HITL resume, or in a
later run in the same session) then took the opposite branch from the one the
same code took in memory.

Run-level ``WorkflowRunOutput.content`` always kept its type, so these tests
pin the step level to the same contract. Values JSON cannot carry still fall
back to ``str()``.
"""

import json
from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel

from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.workflow.types import StepOutput

JSON_NATIVE = [False, True, 0, 7, -3, 0.0, 2.5, "ok", "", [], [1, 2], {}, {"a": 1}, None]


def _roundtrip(output: StepOutput) -> StepOutput:
    """Serialize the way a database write does, including the JSON encoding."""
    return StepOutput.from_dict(json.loads(json.dumps(output.to_dict())))


@pytest.mark.parametrize("content", JSON_NATIVE)
def test_step_content_keeps_its_type(content: Any):
    restored = _roundtrip(StepOutput(step_name="result", content=content))

    assert restored.content == content
    assert type(restored.content) is type(content)
    assert bool(restored.content) == bool(content), "a falsey value must not come back truthy"


@pytest.mark.parametrize("content", JSON_NATIVE)
def test_step_content_matches_run_content_through_a_session(content: Any):
    """The reported path: a whole session saved and restored."""
    session = WorkflowSession(
        session_id="session",
        workflow_id="workflow",
        runs=[
            WorkflowRunOutput(
                workflow_id="workflow",
                run_id="run",
                content=content,
                step_results=[StepOutput(step_name="result", content=content)],
            )
        ],
    )

    run = WorkflowSession.from_dict(json.loads(json.dumps(session.to_dict()))).runs[0]

    assert type(run.step_results[0].content) is type(run.content), "step content drifted from run content"
    assert run.step_results[0].content == content


def test_nested_step_content_keeps_its_type():
    """Parallel, Loop, Condition and Router outputs nest their children."""
    parent = StepOutput(
        step_name="parallel",
        step_type="Parallel",
        steps=[StepOutput(step_name="count", content=0), StepOutput(step_name="approved", content=False)],
    )

    restored = _roundtrip(parent)

    assert [step.content for step in restored.steps or []] == [0, False]
    assert [type(step.content) for step in restored.steps or []] == [int, bool]


def test_pydantic_content_still_serializes_to_a_dict():
    class Report(BaseModel):
        title: str
        score: int

    restored = _roundtrip(StepOutput(step_name="result", content=Report(title="t", score=1)))

    assert restored.content == {"title": "t", "score": 1}


def test_content_json_cannot_carry_still_falls_back_to_str():
    moment = datetime(2026, 1, 2, 3, 4, 5)

    restored = _roundtrip(StepOutput(step_name="result", content=moment))

    assert restored.content == str(moment)
