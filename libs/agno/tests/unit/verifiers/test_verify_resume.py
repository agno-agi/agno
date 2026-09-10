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


def _verification_records(step_results):
    """Every verification record in a run's step results, nested outputs included."""
    records = []

    def walk(outputs):
        for output in outputs or []:
            record = getattr(output, "verification", None)
            if record is not None:
                records.append(record)
            walk(getattr(output, "steps", None))

    walk(step_results)
    return records


def _nested_budget_workflow(tmp_path, name):
    """A Verify with a loop-back segment nested inside a Steps container; the gate always
    fails, and round 2 pauses on the tool confirmation."""
    from agno.workflow.steps import Steps

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
            _text("claimed done"),  # round 1: no tool, gate rejects
            _tool_call("deploy", "c1"),  # round 2 (loop-back): pauses on confirmation
            _text("done after tool"),
        ]
    )
    agent = Agent(model=model, tools=[deploy])
    workflow = Workflow(
        name=name,
        steps=[
            Steps(
                name="gated-segment",
                steps=[Step(name="deployer", agent=agent), Verify(gate, on_fail="deployer", max_rounds=1)],
            ),
        ],
        db=SqliteDb(db_file=str(tmp_path / f"{name}.db")),
    )
    run = workflow.run("go", session_id=f"{name}-session")
    assert run.is_paused, "round 2 must pause on the tool confirmation"
    assert gate_runs["n"] == 1, "one attempt concluded before the pause"
    return workflow, run, gate_runs, model


def test_nested_budget_exhaustion_holds_across_the_pause(tmp_path):
    """The nested twin of test_budget_exhaustion_holds_across_the_pause: the record rides
    the paused Verify output INSIDE the container's wrapper output, and must still be
    found on resume — the resumed round is the LAST round of the window."""
    workflow, run, gate_runs, model = _nested_budget_workflow(tmp_path, "nested-budget")

    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert gate_runs["n"] == 2, "the resumed round is the LAST round of the window"
    assert model.calls == 3, "no segment execution past max_rounds"
    records = _verification_records(resumed.step_results)
    assert records, "the resumed run must carry the gate's record"
    assert records[-1].status == "unverified"
    assert records[-1].stop_reason == "exhausted"
    assert len(records[-1].attempts) == 2, "the pre-pause attempt must survive the pause"


def test_nested_budget_exhaustion_holds_across_the_pause_async(tmp_path):
    """Async twin: the nested gate's budget window survives the pause via acontinue_run."""
    workflow, run, gate_runs, model = _nested_budget_workflow(tmp_path, "nested-budget-async")

    _confirm_all(run)
    resumed = asyncio.run(workflow.acontinue_run(run))

    assert gate_runs["n"] == 2
    assert model.calls == 3
    records = _verification_records(resumed.step_results)
    assert records
    assert records[-1].stop_reason == "exhausted"
    assert len(records[-1].attempts) == 2


def _cross_process_pieces(tmp_path, name):
    """Two workflow objects over one database: the first runs to the pause, the second —
    steps never prepared, as after a server restart — must continue the persisted run."""
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
    agent = Agent(name="deployer-agent", model=model, tools=[deploy])
    db_file = str(tmp_path / f"{name}.db")

    def build():
        return Workflow(
            name=name,
            steps=[Step(name="deployer", agent=agent), Verify(gate, on_fail="deployer", max_rounds=1)],
            db=SqliteDb(db_file=db_file),
        )

    run = build().run("go", session_id=f"{name}-session")
    assert run.is_paused and gate_runs["n"] == 1
    _confirm_all(run)
    return build(), run, gate_runs, model


def test_fresh_workflow_continues_a_persisted_paused_run(tmp_path):
    """Cross-process resume: the continuing workflow object never ran, so its steps were
    never prepared and the Verify never absorbed its segment. continue_run must prepare
    them, resume from storage, and hold the budget window recorded before the restart."""
    fresh, run, gate_runs, model = _cross_process_pieces(tmp_path, "xproc")

    resumed = fresh.continue_run(run_id=run.run_id, session_id="xproc-session", step_requirements=run.step_requirements)

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 2, "exactly one further check pass on resume"
    assert model.calls == 3, "no segment execution past max_rounds"
    records = _verification_records(resumed.step_results)
    assert records, "the resumed run must carry the gate's record"
    assert records[-1].stop_reason == "exhausted"
    assert len(records[-1].attempts) == 2, "the budget window survived the process boundary"


def test_fresh_workflow_continues_a_persisted_paused_run_async(tmp_path):
    """Async twin: acontinue_run on a workflow object whose steps were never prepared."""
    fresh, run, gate_runs, model = _cross_process_pieces(tmp_path, "xproc-async")

    resumed = asyncio.run(
        fresh.acontinue_run(
            run_id=run.run_id, session_id="xproc-async-session", step_requirements=run.step_requirements
        )
    )

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 2
    assert model.calls == 3
    records = _verification_records(resumed.step_results)
    assert records and records[-1].stop_reason == "exhausted"
    assert len(records[-1].attempts) == 2


def _post_gate_shared_agent_workflow(tmp_path, name):
    """A container holding [segment agent step, Verify, post-gate step] where the
    post-gate step reuses the segment's agent, and the pause is in the post-gate step."""
    from agno.workflow.steps import Steps

    gate_runs = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return True

    tool_calls = {"n": 0}

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the change."""
        tool_calls["n"] += 1
        return "deployed"

    model = ScriptedModel(
        [
            _text("segment done"),  # writer inside the segment: passes the gate
            _tool_call("deploy", "c1"),  # editor AFTER the gate: pauses
            _text("done after tool"),
        ]
    )
    agent = Agent(model=model, tools=[deploy])
    workflow = Workflow(
        name=name,
        steps=[
            Steps(
                name="pipeline",
                steps=[
                    Step(name="writer", agent=agent),
                    Verify(gate, on_fail="writer", max_rounds=1),
                    Step(name="editor", agent=agent),
                ],
            ),
        ],
        db=SqliteDb(db_file=str(tmp_path / f"{name}.db")),
    )
    run = workflow.run("go", session_id=f"{name}-session")
    assert run.is_paused, "the post-gate editor must pause on the tool confirmation"
    assert gate_runs["n"] == 1, "the gate concluded before the pause"
    assert tool_calls["n"] == 0
    return workflow, run, gate_runs, tool_calls


def test_post_gate_pause_with_shared_agent_leaves_the_gate_untouched(tmp_path):
    """A pause AFTER the gate, in a step reusing a segment agent, must not hand the
    continued output to the gate: no extra check pass, and the post-gate step's output is
    published as itself, not as a gate output."""
    workflow, run, gate_runs, tool_calls = _post_gate_shared_agent_workflow(tmp_path, "post-gate-shared")

    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1, "the gate must not re-run on an output it was never mounted on"
    assert tool_calls["n"] == 1
    final = (resumed.step_results or [])[-1]
    assert getattr(final, "verification", None) is None, "the continued output must not become a gate output"
    assert final.content == "done after tool"


def test_post_gate_pause_with_shared_agent_leaves_the_gate_untouched_async(tmp_path):
    """Async twin: acontinue_run must not route the post-gate step's output to the gate."""
    workflow, run, gate_runs, tool_calls = _post_gate_shared_agent_workflow(tmp_path, "post-gate-shared-async")

    _confirm_all(run)
    resumed = asyncio.run(workflow.acontinue_run(run))

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1
    assert tool_calls["n"] == 1
    final = (resumed.step_results or [])[-1]
    assert getattr(final, "verification", None) is None
    assert final.content == "done after tool"


def test_async_stream_pause_under_the_gate_persists_paused_not_cancelled(tmp_path):
    """Async-streaming twin of test_resume_runs_the_checks_async: a pause surfacing
    mid-stream must leave the executor run paused. Abandoning the executor's generator
    throws GeneratorExit into it, whose disconnect handling stamps the run cancelled —
    and a cancelled run refuses its resume."""
    import gc

    gate_runs = {"n": 0}

    def gate(run_output):
        gate_runs["n"] += 1
        return True

    tool_calls = {"n": 0}

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the change."""
        tool_calls["n"] += 1
        return "deployed"

    model = ScriptedModel([_tool_call("deploy", "c1"), _text("done after tool")])
    agent = Agent(model=model, tools=[deploy])
    workflow = Workflow(
        name="astream-pause",
        steps=[Step(name="deployer", agent=agent), Verify(gate, on_fail="deployer", max_rounds=1)],
        db=SqliteDb(db_file=str(tmp_path / "astream.db")),
    )

    async def scenario():
        run_id = None
        async for event in workflow.arun("go", session_id="astream-session", stream=True):
            run_id = getattr(event, "run_id", None) or run_id
        run = workflow.get_run_output(run_id=run_id, session_id="astream-session")
        assert run is not None and run.is_paused

        # Force finalization of any abandoned executor generator before the resume; an
        # abandoned generator is closed with GeneratorExit at its suspension point.
        gc.collect()
        await asyncio.sleep(0.05)

        paused_executor_run = (run.step_executor_runs or [])[-1]
        assert paused_executor_run.is_paused, "the executor run must persist as paused, not cancelled"

        _confirm_all(run)
        return await workflow.acontinue_run(run)

    resumed = asyncio.run(scenario())

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1, "the gate must run on resume"
    assert tool_calls["n"] == 1
