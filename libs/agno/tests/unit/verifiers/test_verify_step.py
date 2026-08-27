"""The Verify workflow step, driven through real Workflows on a scripted offline model.

Covers pass-through, loop-back with the evidence report, budget exhaustion, the pure
gate, fatal checks, advisory visibility, the async twin, both streaming paths, and
construction-time errors.
"""

import asyncio
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.verifiers import check
from agno.workflow import Step, Verify, Workflow
from agno.workflow.types import StepOutput


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order, recording the
    messages every call received."""

    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0
        self.seen: List[List[str]] = []

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self

    def _next(self, kwargs: Any) -> ModelResponse:
        self.seen.append([str(m.content) for m in kwargs.get("messages", [])])
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next(kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next(kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def fail_until(threshold: int):
    """A check that fails until its call count reaches the threshold."""
    calls = {"n": 0}

    def report_ready(run_output):
        calls["n"] += 1
        return True if calls["n"] >= threshold else "report is not ready"

    return report_ready


def always_pass(run_output):
    return True


def always_fail(run_output):
    return "never good enough"


def _verify_output(run_output: WorkflowRunOutput) -> StepOutput:
    outputs = [so for so in run_output.step_results if getattr(so, "step_type", None) == "Verify"]
    assert len(outputs) == 1
    return outputs[0]


def test_pass_through():
    writer_model = ScriptedModel([_text("draft")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_pass]),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    verify_output = _verify_output(out)
    assert verify_output.success is True
    assert verify_output.verification.status == "verified"
    assert verify_output.verification.stop_reason == "passed"
    assert len(verify_output.verification.attempts) == 1
    assert writer_model.calls == 1
    assert publisher_model.calls == 1
    # The publisher chained off the verified draft, not off a gate summary.
    assert any("draft" in c for c in publisher_model.seen[0])
    assert out.content == "published"


def test_loop_back_with_evidence():
    writer_model = ScriptedModel([_text("draft one"), _text("draft two")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([fail_until(2)], on_fail="writer", max_rounds=2),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    assert writer_model.calls == 2
    # The re-entered writer received the evidence block, with the failing check named.
    second_call = writer_model.seen[1]
    assert any("<verification" in c for c in second_call)
    assert any("[FAIL] report_ready: report is not ready" in c for c in second_call)
    verify_output = _verify_output(out)
    assert verify_output.success is True
    record = verify_output.verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert len(record.attempts) == 2
    assert record.attempts[0].verdicts[0].passed is False
    assert record.attempts[1].verdicts[0].passed is True
    # The segment ran twice: both writer outputs are nested under the Verify step.
    assert [s.step_name for s in verify_output.steps] == ["writer", "writer"]
    assert publisher_model.calls == 1
    assert out.content == "published"


def test_exhausted():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_fail], on_fail="writer", max_rounds=1),
        ],
    )
    out = workflow.run(input="go")
    assert writer_model.calls == 2
    verify_output = _verify_output(out)
    assert verify_output.success is False
    record = verify_output.verification
    assert record.status == "unverified"
    assert record.stop_reason == "exhausted"
    assert len(record.attempts) == 2
    # The record survives a serialization round-trip as the dataclass, not a dict.
    revived = StepOutput.from_dict(verify_output.to_dict())
    assert revived.verification.status == "unverified"
    assert revived.verification.stop_reason == "exhausted"
    assert len(revived.verification.attempts) == 2
    assert revived.verification.attempts[0].verdicts[0].passed is False


def test_pure_gate():
    writer_model = ScriptedModel([_text("draft")])
    seen = {"n": 0, "contents": []}

    def failing(run_output):
        seen["n"] += 1
        seen["contents"].append(getattr(run_output, "content", None))
        return "not good"

    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([failing], on_fail=None),
        ],
    )
    out = workflow.run(input="go")
    # One check pass, no re-runs.
    assert writer_model.calls == 1
    assert seen["n"] == 1
    # The check judged the previous step's run output.
    assert seen["contents"] == ["draft"]
    verify_output = _verify_output(out)
    assert verify_output.success is False
    record = verify_output.verification
    assert record.status == "unverified"
    assert len(record.attempts) == 1


def test_pure_gate_receives_run_output():
    writer_model = ScriptedModel([_text("draft")])
    captured = {}

    def inspecting(run_output):
        captured["run_output"] = run_output
        return True

    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([inspecting], on_fail=None),
        ],
    )
    workflow.run(input="go")
    # The stored executor run, not just the StepOutput shell, reaches the check.
    assert isinstance(captured["run_output"], RunOutput)
    assert captured["run_output"].content == "draft"


def test_fatal_stops_with_rounds_remaining():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify(
                [check(lambda run_output: "environment is broken", name="env_check", fatal=True)],
                on_fail="writer",
                max_rounds=3,
            ),
        ],
    )
    out = workflow.run(input="go")
    # The fatal failure stopped the loop before any re-run.
    assert writer_model.calls == 1
    verify_output = _verify_output(out)
    assert verify_output.success is False
    record = verify_output.verification
    assert record.status == "unverified"
    assert record.stop_reason == "fatal"
    assert len(record.attempts) == 1


def test_advisory_failure_reported_not_gating():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify(
                [
                    check(lambda run_output: "style could be tighter", name="style", required=False),
                    check(always_pass, name="substance"),
                ]
            ),
        ],
    )
    out = workflow.run(input="go")
    assert writer_model.calls == 1
    verify_output = _verify_output(out)
    assert verify_output.success is True
    record = verify_output.verification
    assert record.status == "verified"
    verdicts = record.attempts[0].verdicts
    advisory = next(v for v in verdicts if v.name == "style")
    assert advisory.passed is False
    assert advisory.required is False
    required = next(v for v in verdicts if v.name == "substance")
    assert required.passed is True


def test_async_loop_back():
    writer_model = ScriptedModel([_text("draft one"), _text("draft two")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([fail_until(2)], on_fail="writer", max_rounds=2),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    out = asyncio.run(workflow.arun(input="go"))
    assert out.status == RunStatus.completed
    assert writer_model.calls == 2
    assert any("<verification" in c for c in writer_model.seen[1])
    verify_output = _verify_output(out)
    assert verify_output.success is True
    assert verify_output.verification.status == "verified"
    assert len(verify_output.verification.attempts) == 2
    assert publisher_model.calls == 1


def test_stream_loop_back():
    writer_model = ScriptedModel([_text("draft one"), _text("draft two")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([fail_until(2)], on_fail="writer", max_rounds=2),
        ],
    )
    events = list(workflow.run(input="go", stream=True, stream_events=True))
    completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed) == 1
    assert writer_model.calls == 2
    assert any("<verification" in c for c in writer_model.seen[1])
    verify_outputs = [so for so in completed[0].step_results if getattr(so, "step_type", None) == "Verify"]
    assert len(verify_outputs) == 1
    assert verify_outputs[0].success is True
    assert verify_outputs[0].verification.status == "verified"


def test_astream_loop_back():
    writer_model = ScriptedModel([_text("draft one"), _text("draft two")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([fail_until(2)], on_fail="writer", max_rounds=2),
        ],
    )

    async def collect():
        out = []
        async for event in workflow.arun(input="go", stream=True, stream_events=True):
            out.append(event)
        return out

    events = asyncio.run(collect())
    completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed) == 1
    assert writer_model.calls == 2
    assert any("<verification" in c for c in writer_model.seen[1])
    verify_outputs = [so for so in completed[0].step_results if getattr(so, "step_type", None) == "Verify"]
    assert len(verify_outputs) == 1
    assert verify_outputs[0].verification.status == "verified"


def test_empty_checks_raise():
    with pytest.raises(ValueError):
        Verify([])


def test_on_fail_naming_a_later_step_raises_before_any_step_runs():
    writer_model = ScriptedModel([_text("draft")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_pass], on_fail="publisher"),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    with pytest.raises(ValueError):
        workflow.run(input="go")
    assert writer_model.calls == 0
    assert publisher_model.calls == 0


def test_on_fail_unknown_name_raises_before_any_step_runs():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_pass], on_fail="ghost"),
        ],
    )
    with pytest.raises(ValueError):
        workflow.run(input="go")
    assert writer_model.calls == 0


def test_default_on_fail_with_no_preceding_step_raises():
    workflow = Workflow(name="wf", steps=[Verify([always_pass])])
    with pytest.raises(ValueError):
        workflow.run(input="go")
