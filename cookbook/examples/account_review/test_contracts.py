"""Exercise the actual pause/continue/save boundary with a deterministic draft."""

import importlib
import sys
from pathlib import Path

import pytest
from agno.workflow.step import Step
from agno.workflow.types import StepOutput


@pytest.mark.parametrize("approve", [True, False])
def test_save_requires_approval(tmp_path, monkeypatch, approve):
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("account_review", None)
    module = importlib.import_module("account_review")

    def draft(step_input):
        return StepOutput(content="Active users fell from 30 to 18.")

    module.workflow.steps[1] = Step(name="Draft review", executor=draft)
    target = Path("approved-review.md")
    target.write_text("Previously approved report")
    result = module.workflow.run("Review Acme")
    assert result.is_paused
    assert target.read_text() == "Previously approved report"
    for requirement in result.steps_requiring_confirmation:
        requirement.confirm() if approve else requirement.reject()
    result = module.workflow.continue_run(result)
    assert not result.is_paused
    assert target.read_text() == (
        "Active users fell from 30 to 18." if approve else "Previously approved report"
    )
