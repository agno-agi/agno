"""HITL resume through the Verify step: a pause inside the absorbed segment must never
carry the workflow past the gate. The workflow's composite-resume seam hands the continued
executor output back to the Verify, which runs the rest of its segment and its checks."""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.verify import Verify
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self

    def _next(self) -> ModelResponse:
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def _tool_call(name: str, call_id: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps({})}}],
    )


def _confirm_all(run_output) -> None:
    for step_req in run_output.step_requirements or []:
        if step_req.requires_executor_input:
            for executor_req in step_req.executor_requirements or []:
                if isinstance(executor_req, dict):
                    executor_req["confirmation"] = True
                    if executor_req.get("tool_execution"):
                        executor_req["tool_execution"]["confirmed"] = True
                else:
                    executor_req.confirm()


def _paused_workflow(tmp_path, gate, name, extra_segment_step=None, publisher=True, max_rounds=1):
    tool_calls = {"n": 0}

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the change."""
        tool_calls["n"] += 1
        return "deployed"

    model = ScriptedModel(
        [
            _tool_call("deploy", "c1"),
            _text("done after tool"),
            _text("done v2"),  # a loop-back re-run of the deployer answers without pausing again
        ]
    )
    agent = Agent(model=model, tools=[deploy])
    steps: List[Any] = [Step(name="deployer", agent=agent)]
    if extra_segment_step is not None:
        steps.append(extra_segment_step)
    steps.append(Verify(gate, on_fail="deployer", max_rounds=max_rounds))
    published = {"n": 0}

    def publish(step_input: StepInput) -> StepOutput:
        published["n"] += 1
        return StepOutput(content="PUBLISHED")

    if publisher:
        steps.append(Step(name="publish", executor=publish))
    workflow = Workflow(name=name, steps=steps, db=SqliteDb(db_file=str(tmp_path / f"{name}.db")))
    run = workflow.run("go", session_id=f"{name}-session")
    assert run.is_paused, "the absorbed tool confirmation must pause the workflow"
    assert tool_calls["n"] == 0
    return workflow, run, tool_calls, published, model


def test_resume_runs_the_checks_and_attaches_the_record(tmp_path):
    gate_runs = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return True

    workflow, run, tool_calls, published, _ = _paused_workflow(tmp_path, gate, "resume-pass")
    assert gate_runs["n"] == 0

    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert tool_calls["n"] == 1
    assert gate_runs["n"] == 1, "the gate must run on resume"
    assert resumed.status == RunStatus.completed
    verify_outputs = [s for s in (resumed.step_results or []) if getattr(s, "verification", None) is not None]
    assert verify_outputs, "the resumed run must carry the Verify output with its record"
    record = verify_outputs[-1].verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert len(record.attempts) == 1
    assert published["n"] == 1, "the publisher runs only after the gate concluded"


def test_resume_failing_gate_loops_back_with_evidence(tmp_path):
    state = {"n": 0}

    def gate(run_output):
        state["n"] += 1
        return True if state["n"] >= 2 else "not good enough yet"

    workflow, run, tool_calls, published, model = _paused_workflow(tmp_path, gate, "resume-loop")
    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    verify_outputs = [s for s in (resumed.step_results or []) if getattr(s, "verification", None) is not None]
    record = verify_outputs[-1].verification
    assert record.status == "verified"
    assert len(record.attempts) == 2, "the failed resume attempt must loop back through the segment"
    assert model.calls == 3, "the loop-back re-ran the deployer agent"
    assert published["n"] == 1


def test_resume_exhausted_gate_ends_unverified(tmp_path):
    def gate(run_output):
        return "never good"

    workflow, run, tool_calls, published, _ = _paused_workflow(tmp_path, gate, "resume-exhaust", max_rounds=0)
    _confirm_all(run)
    resumed = workflow.continue_run(run)

    verify_outputs = [s for s in (resumed.step_results or []) if getattr(s, "verification", None) is not None]
    record = verify_outputs[-1].verification
    assert record.status == "unverified"
    assert record.stop_reason == "exhausted"
    assert verify_outputs[-1].success is False
    assert len(record.attempts) == 1


def test_resume_runs_the_remaining_segment_steps_before_the_checks(tmp_path):
    order: List[str] = []

    def refine(step_input: StepInput) -> StepOutput:
        order.append("refine")
        return StepOutput(content="refined output")

    def gate(run_output):
        order.append("gate")
        return True

    workflow, run, tool_calls, published, _ = _paused_workflow(
        tmp_path, gate, "resume-segment", extra_segment_step=Step(name="refine", executor=refine)
    )
    assert order == []
    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    assert order == ["refine", "gate"], "the segment step after the paused one runs before the checks"


def test_resume_runs_the_checks_async(tmp_path):
    gate_runs = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return True

    workflow, run, tool_calls, published, _ = _paused_workflow(tmp_path, gate, "resume-async")
    _confirm_all(run)
    resumed = asyncio.run(workflow.acontinue_run(run))

    assert gate_runs["n"] == 1
    assert resumed.status == RunStatus.completed
    verify_outputs = [s for s in (resumed.step_results or []) if getattr(s, "verification", None) is not None]
    assert verify_outputs and verify_outputs[-1].verification.status == "verified"
    assert published["n"] == 1


def test_nested_verify_resume_still_runs_the_checks(tmp_path):
    """A Verify nested inside a container must regain control on resume: the seam finds
    the deepest resumable composite, not just a top-level one."""
    from agno.workflow.steps import Steps

    gate_runs = {"n": 0}
    tool_calls = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return True

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the change."""
        tool_calls["n"] += 1
        return "deployed"

    model = ScriptedModel([_tool_call("deploy", "c1"), _text("done after tool")])
    agent = Agent(model=model, tools=[deploy])
    published = {"n": 0}

    def publish(step_input: StepInput) -> StepOutput:
        published["n"] += 1
        return StepOutput(content="PUBLISHED")

    workflow = Workflow(
        name="nested-resume",
        steps=[
            Steps(
                name="gated-segment",
                steps=[Step(name="deployer", agent=agent), Verify(gate, on_fail="deployer", max_rounds=1)],
            ),
            Step(name="publish", executor=publish),
        ],
        db=SqliteDb(db_file=str(tmp_path / "nested.db")),
    )
    run = workflow.run("go", session_id="nested-resume-session")
    assert run.is_paused and gate_runs["n"] == 0

    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1, "the nested gate must run on resume"
    assert tool_calls["n"] == 1
    assert published["n"] == 1


def test_budget_window_survives_the_pause(tmp_path):
    """A verification attempt concluded BEFORE the pause must survive resume: the record
    rides the paused output, so max_rounds holds across pause cycles."""
    gate_runs = {"n": 0}
    tool_calls = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return True if gate_runs["n"] >= 2 else "first attempt rejected"

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the change."""
        tool_calls["n"] += 1
        return "deployed"

    model = ScriptedModel(
        [
            _text("claimed done"),  # round 1: no tool, gate rejects
            _tool_call("deploy", "c1"),  # round 2 (loop-back): pauses on confirmation
            _text("done after tool"),
        ]
    )
    agent = Agent(model=model, tools=[deploy])
    workflow = Workflow(
        name="budget-pause",
        steps=[Step(name="deployer", agent=agent), Verify(gate, on_fail="deployer", max_rounds=1)],
        db=SqliteDb(db_file=str(tmp_path / "budget.db")),
    )
    run = workflow.run("go", session_id="budget-session")
    assert run.is_paused, "round 2 must pause on the tool confirmation"
    assert gate_runs["n"] == 1, "one attempt concluded before the pause"

    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 2, "exactly one further check pass on resume"
    verify_outputs = [s for s in (resumed.step_results or []) if getattr(s, "verification", None) is not None]
    record = verify_outputs[-1].verification
    assert record.status == "verified"
    assert len(record.attempts) == 2, "the pre-pause attempt must survive the pause"
    assert not any(getattr(s, "is_paused", False) for s in (resumed.step_results or [])), (
        "the stale paused placeholder must not survive in step_results"
    )


def test_budget_exhaustion_holds_across_the_pause(tmp_path):
    """GPT's repro: with max_rounds=1 and a failing gate, a pause mid-round-2 must not
    grant extra rounds on resume — two check passes total, then exhausted."""
    gate_runs = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return "never good"

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the change."""
        return "deployed"

    model = ScriptedModel(
        [
            _text("claimed done"),
            _tool_call("deploy", "c1"),
            _text("done after tool"),
        ]
    )
    agent = Agent(model=model, tools=[deploy])
    workflow = Workflow(
        name="budget-exhaust-pause",
        steps=[Step(name="deployer", agent=agent), Verify(gate, on_fail="deployer", max_rounds=1)],
        db=SqliteDb(db_file=str(tmp_path / "budget2.db")),
    )
    run = workflow.run("go", session_id="budget2-session")
    assert run.is_paused and gate_runs["n"] == 1

    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert gate_runs["n"] == 2, "the resumed round is the LAST round of the window"
    verify_outputs = [s for s in (resumed.step_results or []) if getattr(s, "verification", None) is not None]
    record = verify_outputs[-1].verification
    assert record.status == "unverified"
    assert record.stop_reason == "exhausted"
    assert len(record.attempts) == 2
