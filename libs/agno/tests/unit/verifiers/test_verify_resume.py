"""HITL resume through the Verify step: a pause inside the absorbed segment must never
carry the workflow past the gate. The workflow's composite-resume seam hands the continued
executor output back to the Verify, which runs the rest of its segment and its checks."""

import asyncio
import gc
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.tools import tool
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.verify import Verify
from agno.workflow.workflow import Workflow

from .conftest import ScriptedModel, _text, _tool_call, _verification_records

_DEPLOYED: List[str] = []

USE_ASYNC = pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])


@pytest.fixture(autouse=True)
def _reset_deployed():
    _DEPLOYED.clear()


@tool(requires_confirmation=True)
def deploy() -> str:
    """Deploy the change."""
    _DEPLOYED.append("deploy")
    return "deployed"


def _counting_gate(pass_from: Optional[int] = 1) -> Tuple[Callable[[Any], Any], Dict[str, int]]:
    """A check that counts its calls and passes from call `pass_from` on; None never passes."""
    runs = {"n": 0}

    def gate(run_output):
        runs["n"] += 1
        return True if pass_from is not None and runs["n"] >= pass_from else "not good enough yet"

    return gate, runs


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


def _container(kind: str, segment: List[Any]) -> Any:
    if kind == "steps":
        return Steps(name="container", steps=segment)
    if kind == "loop":
        return Loop(name="container", steps=segment, max_iterations=1)
    if kind == "condition":
        return Condition(name="container", evaluator=lambda step_input: True, steps=segment)
    return Router(name="container", selector=lambda step_input: "steps_group_0", choices=[segment])


def _workflow(
    tmp_path,
    name: str,
    gate: Callable[[Any], Any],
    script: List[Any],
    *,
    container: Optional[str] = None,
    post_gate: bool = False,
    extra_segment_step: Optional[Step] = None,
    published: Optional[Dict[str, int]] = None,
    max_attempts: int = 2,
    verify_name: Optional[str] = None,
    fingerprint: Optional[Any] = None,
) -> Tuple[Callable[[], Workflow], ScriptedModel]:
    """A deployer step gated by a Verify, optionally inside a container, with an optional
    post-gate step reusing the segment's agent and an optional publisher after the gate.
    Returns a builder so a test can continue the persisted run on a fresh workflow object."""
    model = ScriptedModel(script)
    agent = Agent(name="deployer-agent", model=model, tools=[deploy])
    first = "writer" if post_gate else "deployer"
    db_file = str(tmp_path / f"{name}.db")

    def publish(step_input: StepInput) -> StepOutput:
        assert published is not None
        published["n"] += 1
        return StepOutput(content="PUBLISHED")

    def build() -> Workflow:
        segment: List[Any] = [Step(name=first, agent=agent)]
        if extra_segment_step is not None:
            segment.append(extra_segment_step)
        segment.append(
            Verify(
                [gate],
                on_fail=first,
                max_attempts=max_attempts,
                name=verify_name,
                fingerprint=fingerprint,
                stop_on_unchanged_state=fingerprint is not None,
            )
        )
        if post_gate:
            segment.append(Step(name="editor", agent=agent))
        steps: List[Any] = [_container(container, segment)] if container else segment
        if published is not None:
            steps.append(Step(name="publish", executor=publish))
        return Workflow(name=name, steps=steps, db=SqliteDb(db_file=db_file))

    return build, model


def _run_to_pause(workflow: Workflow, name: str):
    run = workflow.run("go", session_id=f"{name}-session")
    assert run.is_paused, "the absorbed tool confirmation must pause the workflow"
    return run


# Model scripts: the claimed-done variant spends attempt 1 without the tool, so the pause
# lands in attempt 2.
def _pause_then_done() -> List[Any]:
    return [_tool_call("deploy", "c1"), _text("done after tool"), _text("done v2")]


def _claim_then_pause() -> List[Any]:
    return [_text("claimed done"), _tool_call("deploy", "c1"), _text("done after tool")]


def _gate_then_post_gate_pause() -> List[Any]:
    return [_text("segment done"), _tool_call("deploy", "c1"), _text("done after tool")]


async def _continue(workflow: Workflow, run, use_async: bool, **kwargs):
    if use_async:
        return await workflow.acontinue_run(run, **kwargs)
    return workflow.continue_run(run, **kwargs)


@USE_ASYNC
async def test_resume_runs_the_checks_and_loops_back_with_evidence(tmp_path, use_async):
    name = f"resume-loop-{use_async}"
    gate, gate_runs = _counting_gate(pass_from=2)
    published = {"n": 0}
    build, model = _workflow(tmp_path, name, gate, _pause_then_done(), published=published)
    workflow = build()
    run = _run_to_pause(workflow, name)
    assert _DEPLOYED == []
    assert gate_runs["n"] == 0

    _confirm_all(run)
    resumed = await _continue(workflow, run, use_async)

    assert len(_DEPLOYED) == 1
    assert gate_runs["n"] == 2, "the gate runs on resume, then again after the loop-back"
    assert resumed.status == RunStatus.completed
    record = _verification_records(resumed.step_results)[-1]
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert len(record.attempts) == 2, "the failed resume attempt must loop back through the segment"
    assert model.calls == 3, "the loop-back re-ran the deployer agent"
    assert published["n"] == 1, "the publisher runs only after the gate concluded"


def test_resume_runs_the_remaining_segment_steps_before_the_checks(tmp_path):
    order: List[str] = []

    def refine(step_input: StepInput) -> StepOutput:
        order.append("refine")
        return StepOutput(content="refined output")

    def gate(run_output):
        order.append("gate")
        return True

    build, _ = _workflow(
        tmp_path,
        "resume-segment",
        gate,
        _pause_then_done(),
        published={"n": 0},
        extra_segment_step=Step(name="refine", executor=refine),
    )
    workflow = build()
    run = _run_to_pause(workflow, "resume-segment")
    assert order == []
    _confirm_all(run)
    resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    assert order == ["refine", "gate"], "the segment step after the paused one runs before the checks"


class _ConstantFingerprint:
    def capture(self) -> str:
        return "same"


@pytest.mark.parametrize(
    "container, fresh, unchanged",
    [
        (None, False, False),
        (None, True, False),
        ("steps", False, False),
        ("steps", True, False),
        (None, False, True),
    ],
    ids=["top-level", "top-level-fresh", "nested", "nested-fresh", "unchanged-state"],
)
@USE_ASYNC
async def test_budget_exhaustion_holds_across_the_pause(tmp_path, container, fresh, unchanged, use_async):
    """With max_attempts=2 and a failing gate, a pause mid-attempt-2 must not grant extra
    attempts on resume: two check passes total, then exhausted. Nested, the record rides the
    paused Verify output inside the container's wrapper output and must still be found. A
    workflow object that never ran continues from storage with the same window. A resumed
    attempt that changed nothing since the pre-pause baseline stops as unchanged_state."""
    name = f"budget-exhaust-{container}-{fresh}-{unchanged}-{use_async}"
    gate, gate_runs = _counting_gate(pass_from=None)
    script = _pause_then_done() if unchanged else _claim_then_pause()
    fingerprint = _ConstantFingerprint() if unchanged else None
    build, model = _workflow(tmp_path, name, gate, script, container=container, fingerprint=fingerprint)
    workflow = build()
    run = _run_to_pause(workflow, name)
    assert gate_runs["n"] == (0 if unchanged else 1)

    _confirm_all(run)
    if fresh:
        kwargs = dict(run_id=run.run_id, session_id=f"{name}-session", step_requirements=run.step_requirements)
        continuing = build()
        resumed = await continuing.acontinue_run(**kwargs) if use_async else continuing.continue_run(**kwargs)
    else:
        resumed = await _continue(workflow, run, use_async)

    # The gate is the run's last word and never passed: the run is unverified.
    assert resumed.status == RunStatus.unverified
    records = _verification_records(resumed.step_results)
    assert records, "the resumed run must carry the gate's record"
    assert records[-1].status == "unverified"
    if unchanged:
        assert records[-1].stop_reason == "unchanged_state"
        assert len(records[-1].attempts) == 1
        assert model.calls == 2, "an unchanged resumed attempt does not re-enter the segment"
        return
    assert gate_runs["n"] == 2, "the resumed attempt is the last attempt of the window"
    assert model.calls == 3, "no segment execution past max_attempts"
    assert records[-1].stop_reason == "exhausted"
    assert len(records[-1].attempts) == 2, "the pre-pause attempt must survive the pause"


@pytest.mark.parametrize("kind", ["steps", "loop", "condition", "router"])
@pytest.mark.parametrize("fresh", [False, True], ids=["same_object", "fresh_object"])
def test_post_gate_pause_with_shared_agent_leaves_the_gate_untouched(tmp_path, kind, fresh):
    """A pause after the gate, in a step reusing a segment agent, must not hand the
    continued output to the gate: no extra check pass, and the post-gate step's output is
    published as itself, not as a gate output. Holds when a workflow object that never ran
    continues the persisted run."""
    name = f"post-gate-shared-{kind}-{fresh}"
    gate, gate_runs = _counting_gate()
    build, _ = _workflow(tmp_path, name, gate, _gate_then_post_gate_pause(), container=kind, post_gate=True)
    workflow = build()
    run = _run_to_pause(workflow, name)
    assert gate_runs["n"] == 1, "the gate concluded before the pause"
    assert _DEPLOYED == []

    _confirm_all(run)
    if fresh:
        resumed = build().continue_run(
            run_id=run.run_id, session_id=f"{name}-session", step_requirements=run.step_requirements
        )
    else:
        resumed = workflow.continue_run(run)

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1, "the gate must not re-run on an output it was never mounted on"
    assert len(_DEPLOYED) == 1
    final = (resumed.step_results or [])[-1]
    while getattr(final, "steps", None):
        final = final.steps[-1]
    assert getattr(final, "verification", None) is None, "the continued output must not become a gate output"
    assert final.content == "done after tool"


async def test_async_stream_pause_under_the_gate_persists_paused_not_cancelled(tmp_path):
    """A pause surfacing mid-stream must leave the executor run paused. Abandoning the
    executor's generator throws GeneratorExit into it, whose disconnect handling stamps the
    run cancelled, and a cancelled run refuses its resume."""
    gate, gate_runs = _counting_gate()
    build, _ = _workflow(tmp_path, "astream-pause", gate, _pause_then_done())
    workflow = build()

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
    resumed = await workflow.acontinue_run(run)

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1, "the gate must run on resume"
    assert len(_DEPLOYED) == 1


@USE_ASYNC
async def test_stream_resume_emits_the_gate_events(tmp_path, use_async):
    """A streaming continue through the gate emits its attempt and completion events like a
    fresh stream does: the resumed attempt's verdict, then the re-entered attempt, then the end."""
    name = f"stream-resume-{use_async}"
    gate, _ = _counting_gate(pass_from=2)
    build, _ = _workflow(tmp_path, name, gate, _pause_then_done(), verify_name="gate")
    workflow = build()
    run = _run_to_pause(workflow, name)
    _confirm_all(run)

    if use_async:
        events = [e async for e in await workflow.acontinue_run(run, stream=True, stream_events=True)]
    else:
        events = list(workflow.continue_run(run, stream=True, stream_events=True))

    names = [e.event for e in events if "Verify" in getattr(e, "event", "")]
    assert names == [
        "VerifyAttemptCompleted",
        "VerifyAttemptStarted",
        "VerifyAttemptCompleted",
        "VerifyExecutionCompleted",
    ]
    final = workflow.get_run_output(run_id=run.run_id, session_id=f"{name}-session")
    assert final.status == RunStatus.completed
    assert len(final.step_results[-1].verification.attempts) == 2


def test_nested_stream_resume_keeps_its_placement_across_two_pauses(tmp_path):
    """A gate nested in a container pauses twice, then fails once and re-enters; every
    continue emits its events at the index and under the parent id the pre-pause events
    carried, and the re-entered attempt nests its steps under the gate's own step id."""
    gate, gate_runs = _counting_gate(pass_from=2)
    build, _ = _workflow(
        tmp_path,
        "nested-twice",
        gate,
        [_tool_call("deploy", "c1"), _tool_call("deploy", "c2"), _text("done"), _text("done v2")],
        container="steps",
        max_attempts=3,
        verify_name="gate",
    )
    workflow = build()

    def gate_events(events):
        return [(e.step_index, e.parent_step_id) for e in events if "Verify" in getattr(e, "event", "")]

    def deployer_parents(events):
        return [
            e.parent_step_id for e in events if getattr(e, "event", "") == "StepStarted" and e.step_name == "deployer"
        ]

    first = list(workflow.run("go", session_id="s", stream=True, stream_events=True))
    fresh = gate_events(first)
    run = workflow.get_run_output(run_id=workflow.get_last_run_output(session_id="s").run_id, session_id="s")
    _confirm_all(run)
    list(workflow.continue_run(run, stream=True, stream_events=True))
    run = workflow.get_last_run_output(session_id="s")
    assert run.is_paused and len(_DEPLOYED) == 1
    _confirm_all(run)
    last = list(workflow.continue_run(run, stream=True, stream_events=True))
    resumed = gate_events(last)
    assert fresh and fresh[0] == ((0, 0), fresh[0][1]) and fresh[0][1] is not None
    assert resumed and all(placement == fresh[0] for placement in resumed)
    assert gate_runs["n"] == 2, "the resumed attempt failed and the gate re-entered"
    assert len(deployer_parents(last)) == 1
    assert deployer_parents(last) == deployer_parents(first)
    assert workflow.get_last_run_output(session_id="s").status == RunStatus.completed


def _paused_gate_rows(step_results):
    return [s for s in (step_results or []) if getattr(s, "is_paused", False) and s.step_name == "gate"]


@USE_ASYNC
async def test_second_pause_cycle_replaces_the_paused_placeholder(tmp_path, use_async):
    """Two consecutive tool confirmations inside the segment: each pause persists one
    placeholder for the gate, and the gate's own attempt carries only the live outputs."""
    name = f"twice-{use_async}"
    build, _ = _workflow(
        tmp_path,
        name,
        lambda run_output: True,
        [_tool_call("deploy", "c1"), _tool_call("deploy", "c2"), _text("done after tools")],
        max_attempts=3,
        verify_name="gate",
    )
    workflow = build()
    first = _run_to_pause(workflow, name)
    assert len(_paused_gate_rows(first.step_results)) == 1

    _confirm_all(first)
    second = await _continue(workflow, first, use_async)
    assert second.is_paused, "the second tool call pauses again"
    assert len(_DEPLOYED) == 1
    rows = _paused_gate_rows(second.step_results)
    assert len(rows) == 1, "a new pause cycle replaces the previous placeholder"
    assert len([s for s in rows[0].steps if getattr(s, "is_paused", False)]) == 1

    _confirm_all(second)
    final = await _continue(workflow, second, use_async)
    assert final.status == RunStatus.completed
    assert len(_DEPLOYED) == 2
    assert not any(getattr(s, "is_paused", False) for s in final.step_results)
    assert final.step_results[-1].step_name == "gate"
    assert len(final.step_results) == 1


@pytest.mark.parametrize("kind", ["loop", "condition", "router"])
def test_fresh_workflow_runs_a_nested_gate_on_resume(tmp_path, kind):
    """A nested gate on a workflow object that never ran: the containers are prepared
    with the workflow, so the resume seam finds the gate and runs its checks."""
    name = f"xproc-{kind}"
    gate, gate_runs = _counting_gate()
    published = {"n": 0}
    build, _ = _workflow(tmp_path, name, gate, _pause_then_done(), container=kind, published=published)
    run = _run_to_pause(build(), name)
    assert gate_runs["n"] == 0
    _confirm_all(run)

    resumed = build().continue_run(
        run_id=run.run_id, session_id=f"{name}-session", step_requirements=run.step_requirements
    )

    assert resumed.status == RunStatus.completed
    assert gate_runs["n"] == 1, "the nested gate must run on resume"
    assert published["n"] == 1
