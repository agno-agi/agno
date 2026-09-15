"""The Verify workflow step, driven through real Workflows on a scripted offline model.

Covers loop-back with the evidence report, the pure gate, stop_on_failure checks, placement
errors, the terminal run status and answer a gate decides, the AgentOS run listing, events,
printers, serialization, and the unverified agent step inside a workflow.
"""

import io
from typing import Any, List, Optional

import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.os import AgentOS
from agno.os.utils import collect_components_from_workflow, collect_mcp_tools_from_workflow
from agno.registry import Registry
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.workflow import (
    VerifyAttemptCompletedEvent,
    VerifyAttemptStartedEvent,
    VerifyExecutionCompletedEvent,
    VerifyExecutionStartedEvent,
    WorkflowRunOutput,
    workflow_run_output_event_from_dict,
)
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools
from agno.verifiers import VerificationConfig, verifier
from agno.verifiers.types import Verification
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Verify, Workflow
from agno.workflow.step import UnresolvableCallableError
from agno.workflow.types import HumanReview, StepInput, StepOutput
from agno.workflow.verify import UnresolvedVerifyError, resolve_verify_steps

from .conftest import (
    ScriptedModel,
    _run_path,
    _text,
    _verification_records,
    always_fail,
    always_pass,
    fail_once,
)


def _verify_output(run_output: WorkflowRunOutput) -> StepOutput:
    """The run's single Verify output, found at any nesting depth."""

    def flatten(outputs):
        for output in outputs or []:
            yield output
            yield from flatten(getattr(output, "steps", None))

    (gate,) = [s for s in flatten(run_output.step_results) if getattr(s, "step_type", None) == "Verify"]
    return gate


def _writer(*drafts: str) -> Step:
    script = [_text(draft) for draft in drafts or ("draft",)]
    return Step(name="writer", agent=Agent(name="writer", model=ScriptedModel(script)))


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream", [False, True])
async def test_loop_back_with_evidence(use_async, stream):
    writer_model = ScriptedModel([_text("draft one"), _text("draft two")])
    refine_inputs: List[Optional[str]] = []
    seen = {}

    def refine(step_input: StepInput) -> StepOutput:
        refine_inputs.append(step_input.get_last_step_content())
        return StepOutput(content=f"refined {step_input.previous_step_content}")

    def publisher(step_input: StepInput) -> StepOutput:
        seen["previous"] = step_input.previous_step_content
        seen["writer"] = step_input.get_step_content("writer")
        return StepOutput(content="published")

    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Step(name="refine", executor=refine),
            Verify([fail_once()], on_fail="writer", max_attempts=3),
            Step(name="publisher", executor=publisher),
        ],
    )
    out = await _run_path(workflow, use_async, stream, input="Write the launch brief", stream_events=stream)
    assert out.status == RunStatus.completed
    assert writer_model.calls == 2
    # The re-entered writer received the evidence block, with the failing check named, after
    # the original task and the previous draft.
    second_call = writer_model.seen[1]
    reentry = next(c for c in second_call if "<verification" in c)
    assert "[FAIL] report_exists: report.md is missing" in reentry
    assert reentry.index("Write the launch brief") < reentry.index("draft one") < reentry.index("<verification")
    # Attempt 2's refine step chains off the writer's attempt-2 draft, not the evidence entry.
    assert refine_inputs == ["draft one", "draft two"]
    verify_output = _verify_output(out)
    assert verify_output.success is True
    record = verify_output.verification
    assert record.status == "verified"
    assert record.stop_reason == "passed"
    assert len(record.attempts) == 2
    assert record.attempts[0].verdicts[0].passed is False
    assert record.attempts[1].verdicts[0].passed is True
    # The accepted attempt sits on the Verify step's steps, the rejected one under previous_attempts.
    assert [s.step_name for s in verify_output.steps] == ["writer", "refine"]
    assert verify_output.steps[-1].content == "refined draft two"
    assert [[s.content for s in r] for r in verify_output.previous_attempts] == [["draft one", "refined draft one"]]
    # The publisher chained off the verified draft, not off a gate summary, and finds the accepted round.
    assert seen == {"previous": "refined draft two", "writer": "draft two"}
    assert out.content == "published"


def test_stop_on_failure_stops_with_attempts_remaining():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify(
                [verifier(lambda run_output: "environment is broken", name="env_check", stop_on_failure=True)],
                on_fail="writer",
                max_attempts=4,
            ),
        ],
    )
    out = workflow.run(input="go")
    # The stop_on_failure check stopped the loop before any re-run.
    assert writer_model.calls == 1
    verify_output = _verify_output(out)
    assert verify_output.success is False
    record = verify_output.verification
    assert record.status == "unverified"
    assert record.stop_reason == "fatal"
    assert len(record.attempts) == 1


def test_empty_checks_raise():
    with pytest.raises(ValueError):
        Verify([])


@pytest.mark.parametrize(
    "case, message",
    [
        ("later_step", "not a step before it"),
        ("no_preceding", "no preceding step"),
        ("pure_gate_first", "pure gate with no step before it"),
        ("crosses_gate", "'second' cannot re-run another gate, Verify 'first'"),
        ("human_review", "cannot absorb"),
    ],
)
def test_invalid_placement_raises_at_build(case, message):
    ran = {"n": 0}

    def draft(step_input: StepInput) -> StepOutput:
        ran["n"] += 1
        return StepOutput(content="draft")

    writer = Step(name="writer", executor=draft)
    steps: List[Any] = {
        "later_step": lambda: [
            writer,
            Verify([always_pass], on_fail="publisher"),
            Step(name="publisher", executor=draft),
        ],
        "no_preceding": lambda: [Verify([always_pass])],
        "pure_gate_first": lambda: [Verify([always_pass], on_fail=None), writer],
        "crosses_gate": lambda: [
            writer,
            Verify([always_pass], on_fail=None, name="first"),
            Verify([always_pass], on_fail="writer", name="second"),
        ],
        "human_review": lambda: [
            Step(name="writer", executor=draft, human_review=HumanReview(requires_confirmation=True)),
            Verify([always_pass], on_fail="writer"),
        ],
    }[case]()
    with pytest.raises(ValueError, match=message):
        Workflow(name="wf", steps=steps).run(input="go")
    assert ran["n"] == 0


# ---------------------------------------------------------------------------
# Cross-workflow reuse
# ---------------------------------------------------------------------------


def test_cross_workflow_reuse_raises_and_same_workflow_rerun_survives():
    shared = Verify([always_pass], on_fail="writer")
    model_a = ScriptedModel([_text("a")])
    model_b = ScriptedModel([_text("b")])
    wf_a = Workflow(name="wf_a", steps=[Step(name="writer", agent=Agent(name="writer", model=model_a)), shared])
    wf_b = Workflow(name="wf_b", steps=[Step(name="writer", agent=Agent(name="writer", model=model_b)), shared])

    out_a = wf_a.run(input="go")
    assert out_a.status == RunStatus.completed
    # The second workflow must refuse the already-bound Verify instead of silently
    # running the first workflow's absorbed segment.
    with pytest.raises(ValueError, match="already bound to another workflow"):
        wf_b.run(input="go")
    assert model_b.calls == 0
    # Same-workflow re-prepare stays idempotent after the refusal.
    out_a2 = wf_a.run(input="go")
    assert out_a2.status == RunStatus.completed


def test_deep_copied_workflow_rebinds_verify_owner():
    # A deep copy is a fresh mount, not a reuse: it must run cleanly and its checks must
    # see the copy as their owner, not the stale original.
    owners = []

    def owner_check(run_output, workflow):
        owners.append(workflow)
        return True

    def writer(step_input: StepInput) -> StepOutput:
        return StepOutput(content="draft")

    original = Workflow(
        name="wf", steps=[Step(name="writer", executor=writer), Verify([owner_check], on_fail="writer")]
    )
    assert original.run(input="go").status == RunStatus.completed
    copied = original.deep_copy()
    assert copied.run(input="go").status == RunStatus.completed
    assert owners[0] is original
    assert owners[1] is copied


# ---------------------------------------------------------------------------
# Pure-gate content forwarding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("before", ["loop", "verify"])
def test_pure_gate_after_a_composite_forwards_real_content(before):
    seen = {}

    def printer(step_input: StepInput) -> StepOutput:
        seen["content"] = step_input.previous_step_content
        return StepOutput(content="printer done")

    if before == "loop":
        body = Step(name="body", executor=lambda step_input: StepOutput(content="draft"))
        steps: List[Any] = [
            Loop(name="loop", steps=[body], max_iterations=1),
            Verify([always_pass], on_fail=None, name="gate"),
            Step(name="printer", executor=printer),
        ]
    else:
        # A gate after a gate runs as a pure gate on the first gate's accepted output.
        steps = [
            Step(name="writer", executor=lambda step_input: StepOutput(content="draft")),
            Verify([always_pass], on_fail="writer", name="first"),
            Verify([always_pass], on_fail=None, name="gate"),
        ]
    out = Workflow(name="wf", steps=steps).run(input="go")
    assert out.status == RunStatus.completed
    gate_output = next(so for so in out.step_results if so.step_name == "gate")
    # The gate forwards the composite's real work, not its summary line.
    assert gate_output.content == "draft"
    if before == "loop":
        assert seen["content"] == "draft"
    else:
        assert [s.step_name for s in out.step_results] == ["first", "gate"]
        assert out.content == "draft"


# ---------------------------------------------------------------------------
# Router choices and Parallel branches
# ---------------------------------------------------------------------------


def _container(kind: str, *steps: Any) -> Any:
    """A Router selecting the last step, or a Parallel running every step."""
    if kind == "router":
        return Router(name="router", selector=lambda step_input: steps[-1].name, choices=list(steps))
    return Parallel(*steps, name="par")


def _side() -> Step:
    return Step(name="side", executor=lambda step_input: StepOutput(content="side"))


@pytest.mark.parametrize("when", ["construct", "swapped"])
@pytest.mark.parametrize("kind", ["router", "parallel"])
def test_direct_verify_with_on_fail_in_a_container_raises(kind, when):
    # A Parallel branch raise at execution time is absorbed by the aggregation and the run
    # completes with zero checks executed, so the refusal must land at build time; choices or
    # steps replaced after construction must still be refused by the container's preparation.
    if when == "construct":
        with pytest.raises(ValueError, match="is a Verify with on_fail"):
            _container(kind, _side(), Verify([always_pass], name="checked"))
        return
    writer_model = ScriptedModel([_text("draft")])
    container = _container(kind, Step(name="other", executor=lambda step_input: StepOutput(content="other")))
    workflow = Workflow(
        name="wf",
        steps=[Step(name="writer", agent=Agent(name="writer", model=writer_model)), container],
    )
    bad = [Verify([always_pass], name="checked")]
    if kind == "router":
        container.choices = bad
        container.selector = lambda step_input: "checked"
    else:
        container.steps = bad
    with pytest.raises(ValueError, match="is a Verify with on_fail"):
        workflow.run(input="go")
    assert writer_model.calls == 0


@pytest.mark.parametrize("kind", ["router", "parallel"])
def test_direct_pure_gate_in_a_container_passes(kind):
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            _container(kind, _side(), Verify([always_pass], on_fail=None, name="gate")),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    assert writer_model.calls == 1


def test_router_list_route_verify_second_run_does_not_double_execute():
    # Router rebuilds its list-route Steps wrapper from raw choices every run, so from
    # the second run the resolver sees an already-resolved Verify next to the segment
    # step it absorbed on run one; the segment must not survive at the container level.
    ran = {"fix": 0}

    def fix(step_input: StepInput) -> StepOutput:
        ran["fix"] += 1
        return StepOutput(content="fixed")

    workflow = Workflow(
        name="wf",
        steps=[
            Router(
                name="router",
                selector=lambda step_input: "steps_group_0",
                choices=[
                    [
                        Step(name="fix", executor=fix),
                        Verify([always_fail], on_fail="fix", max_attempts=2, name="checked"),
                    ]
                ],
            ),
        ],
    )
    out_first = workflow.run(input="go")
    assert out_first.status == RunStatus.unverified
    # Initial attempt plus one loop-back: the segment ran exactly twice.
    first_run_executions = ran["fix"]
    assert first_run_executions == 2
    out_second = workflow.run(input="go")
    assert out_second.status == RunStatus.unverified
    # The second run executes the segment once per attempt, exactly like the first.
    assert ran["fix"] - first_run_executions == first_run_executions


# ---------------------------------------------------------------------------
# Structural walks over a resolved Verify
# ---------------------------------------------------------------------------


def test_studio_walks_see_the_absorbed_segment_agent(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "pins.db"))
    Agent(id="seg-agent", name="Seg").save(db=db)
    workflow = Workflow(
        id="wf-pins",
        name="wf",
        steps=[Step(name="writer", agent=Agent(id="seg-agent", name="Seg")), Verify([always_pass], on_fail="writer")],
    )
    workflow.steps = resolve_verify_steps(workflow.steps, owner=workflow)
    assert [type(s).__name__ for s in workflow.steps] == ["Verify"]

    studio = StudioTools(registry=Registry(dbs=[db]), db=db)
    links = studio._links_for_component(workflow) or []
    assert any(
        link.get("link_kind") == "step_agent" and link.get("child_component_id") == "seg-agent" for link in links
    )
    occurrences = StudioRunnerTools._step_occurrences(workflow)
    assert any(kind == "step_agent" and ref_id == "seg-agent" for kind, _key, _ref_type, ref_id, _obj in occurrences)


def gate_check(run_output):
    return True


def fix_it(step_input: StepInput) -> StepOutput:
    return StepOutput(content="fixed")


def test_check_and_executor_sharing_a_name_do_not_collide_in_the_registry():
    def fix(run_output):
        return True

    checked = Verify([verifier(fix, name="fix_it")], on_fail="fix", name="gate")
    workflow = Workflow(
        name="wf",
        steps=[
            Router(
                name="router",
                selector=lambda step_input: "steps_group_0",
                choices=[[Step(name="fix", executor=fix_it), checked]],
            )
        ],
    )
    registry = Registry()
    collect_components_from_workflow(workflow, registry, set())
    # The check inside the list route registers under the prefixed check key, next to the
    # executor of the same name; without it, rehydration degrades the gate to a placeholder.
    assert registry.get_function("fix_it") is fix_it
    assert registry.get_function("verify:fix_it").__wrapped__ is fix
    # Rehydration resolves the check through the prefixed key, not the executor.
    restored = Verify.from_dict(checked.to_dict(), registry=registry)
    assert restored._verifiers[0].name == "fix_it"
    assert restored._verifiers[0].fn.__wrapped__ is fix


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def advisory(run_output):
    return "style could be tighter"


def gatekeeper(run_output):
    return True


async def test_workflow_run_refuses_an_async_check_before_the_segment_runs():
    async def async_check(run_output):
        return True

    calls = {"n": 0}

    def writer(step_input: StepInput) -> StepOutput:
        calls["n"] += 1
        return StepOutput(content="draft")

    workflow = Workflow(name="wf", steps=[Step(name="writer", executor=writer), Verify([async_check], name="gate")])
    with pytest.raises(ValueError, match=r"Cannot use async_check \(an async verifier\) with `run\(\)`"):
        workflow.run("go")
    assert calls["n"] == 0
    assert (await workflow.arun("go")).status == RunStatus.completed
    assert calls["n"] == 1


def test_serialization_round_trip_preserves_per_check_policy():
    class Fingerprint:
        def capture(self):
            return "state"

    original = Verify(
        [verifier(advisory, required=False, max_retries=2), verifier(gatekeeper, stop_on_failure=True)],
        on_fail=None,
        max_attempts=4,
        stop_on_unverified=True,
        stop_on_unchanged_state=True,
        fingerprint=Fingerprint(),
        name="rt",
    )
    data = original.to_dict()
    assert data["on_fail"] is None
    assert data["stop_on_unchanged_state"] is True
    assert data["verifiers"] == [
        {"name": "advisory", "required": False, "max_retries": 2, "stop_on_failure": False},
        {"name": "gatekeeper", "required": True, "max_retries": 0, "stop_on_failure": True},
    ]
    registry = Registry(functions=[advisory, gatekeeper])
    restored = Verify.from_dict(data, registry=registry)
    assert restored.on_fail is None
    assert restored.max_attempts == 4
    assert restored.stop_on_unverified is True
    # The fingerprint is not restored, so unchanged-state detection is turned off.
    assert restored.stop_on_unchanged_state is False
    advisory_wrapper, gatekeeper_wrapper = restored._verifiers
    assert advisory_wrapper.required is False
    assert advisory_wrapper.max_retries == 2
    assert advisory_wrapper.stop_on_failure is False
    assert gatekeeper_wrapper.required is True
    assert gatekeeper_wrapper.stop_on_failure is True

    # The restored advisory check must not re-gate: a failing advisory next to a passing
    # required check still verifies.
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf", steps=[Step(name="writer", agent=Agent(name="writer", model=writer_model)), restored]
    )
    out = workflow.run(input="go")
    verify_output = _verify_output(out)
    assert verify_output.success is True
    assert verify_output.verification.status == "verified"


def test_scorer_verifier_rehydration_names_what_it_cannot_rebuild():
    class Judge:
        name = "judge"

        def verify(self, run_output):
            return True

    original = Verify([Judge()], on_fail=None, name="judged")
    data = original.to_dict()
    assert data["verifiers"][0]["type"] == "protocol"
    restored = Verify.from_dict(data, registry=Registry())
    # The placeholder stops on failure: one failing pass ends the gate without spending attempts.
    assert restored._verifiers[0].stop_on_failure is True

    with pytest.raises(ComponentRehydrationError):
        Verify.from_dict(data, registry=Registry(), strict=True)


def test_registry_miss_placeholder_stops_on_failure_and_ends_the_gate_on_the_first_pass():
    data = {
        "type": "Verify",
        "name": "gone",
        "verifiers": [{"name": "missing", "required": True}],
        "on_fail": "writer",
        "max_attempts": 3,
    }
    restored = Verify.from_dict(data, registry=Registry())
    assert restored._verifiers[0].stop_on_failure is True
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf", steps=[Step(name="writer", agent=Agent(name="writer", model=writer_model)), restored]
    )
    out = workflow.run(input="go")
    assert writer_model.calls == 1
    record = _verify_output(out).verification
    assert record.status == "unverified"
    assert record.stop_reason == "fatal"


def test_workflow_listing_describes_the_gate():
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", executor=lambda step_input: StepOutput(content="draft")),
            Verify([verifier(always_pass, name="ok")], on_fail="writer", max_attempts=4, stop_on_unverified=True),
        ],
    )
    listed = workflow.to_dict_for_steps()["steps"]
    assert len(listed) == 1
    gate = listed[0]
    assert gate["type"] == "Verify"
    assert gate["verifiers"] == ["ok"]
    assert gate["on_fail"] == "writer"
    assert gate["max_attempts"] == 4
    assert gate["stop_on_unverified"] is True
    assert [s["name"] for s in gate["steps"]] == ["writer"]


def test_router_list_route_with_verify_round_trips():
    router = Router(
        name="router",
        selector=lambda step_input: "steps_group_0",
        choices=[[Step(name="fix", executor=fix_it), Verify([gate_check], on_fail="fix", name="checked")]],
    )
    data = router.to_dict()
    assert data["choices"][0]["type"] == "Steps"
    assert data["choices"][0]["list_route"] is True
    assert [s["name"] for s in data["choices"][0]["steps"]] == ["fix", "checked"]

    registry = Registry(functions=[fix_it, gate_check])
    restored = Router.from_dict(data, registry=registry)
    assert isinstance(restored.choices[0], list)
    assert [s.name for s in restored.choices[0]] == ["fix", "checked"]
    assert isinstance(restored.choices[0][1], Verify)
    restored.selector = lambda step_input: "steps_group_0"
    workflow = Workflow(name="wf", steps=[restored])
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    records = _verification_records(out.step_results)
    assert records and records[0].status == "verified"


def test_workflow_run_output_round_trips_verification():
    workflow = Workflow(name="wf", steps=[_writer(), Verify([always_fail], on_fail="writer", max_attempts=1)])
    out = workflow.run(input="go")
    revived = WorkflowRunOutput.from_dict(out.to_dict())
    assert revived.status == RunStatus.unverified
    assert revived.verification is not None and revived.verification.status == "unverified"
    # The step-level record survives a round trip as the dataclass, not a dict.
    step = StepOutput.from_dict(_verify_output(out).to_dict())
    assert step.verification.status == "unverified"
    assert step.verification.stop_reason == "exhausted"
    assert len(step.verification.attempts) == 1
    assert step.verification.attempts[0].verdicts[0].passed is False


# ---------------------------------------------------------------------------
# Step-level policy absorption and segment mechanics
# ---------------------------------------------------------------------------


def test_condition_with_default_review_builds_inside_the_segment():
    # Condition's default human_review differs from a Step's only in on_reject, which the
    # gate never enforces anyway; only the unenforceable fields refuse absorption.

    ran = {"n": 0}

    def body(step_input: StepInput) -> StepOutput:
        ran["n"] += 1
        return StepOutput(content="body")

    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", executor=lambda step_input: StepOutput(content="draft")),
            Condition(name="maybe", evaluator=lambda step_input: True, steps=[Step(name="body", executor=body)]),
            Verify([fail_once()], on_fail="writer", max_attempts=2),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    assert ran["n"] == 2


class CountingFingerprint:
    def __init__(self) -> None:
        self.captures = 0

    def capture(self) -> str:
        self.captures += 1
        return "state"


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream", [False, True])
async def test_fingerprint_settles_only_on_reenter(use_async, stream):
    # Baseline, attempt one, the settle before the re-run, attempt two. A settle after the
    # terminal attempt would be a fifth capture.
    fingerprint = CountingFingerprint()
    workflow = Workflow(
        name="wf",
        steps=[
            _writer("draft one", "draft two"),
            Verify([fail_once()], on_fail="writer", max_attempts=3, fingerprint=fingerprint),
        ],
    )
    out = await _run_path(workflow, use_async, stream, input="go")
    assert _verify_output(out).success is True
    assert fingerprint.captures == 4


def test_early_stop_inside_the_segment_is_not_a_success():
    def stopper(step_input: StepInput) -> StepOutput:
        return StepOutput(content="halt", stop=True)

    checks = {"n": 0}

    def counting(run_output):
        checks["n"] += 1
        return True

    workflow = Workflow(
        name="wf",
        steps=[Step(name="stopper", executor=stopper), Verify([counting], on_fail="stopper")],
    )
    out = workflow.run(input="go")
    gate = _verify_output(out)
    assert gate.stop is True
    assert gate.success is False
    assert gate.verification.status == "pending"
    assert checks["n"] == 0


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream", [False, True])
async def test_raising_segment_step_becomes_a_failed_output(use_async, stream):
    def broken(step_input: StepInput) -> StepOutput:
        raise RuntimeError("segment exploded")

    judged = []

    def gate(run_output):
        judged.append(getattr(run_output, "success", None))
        return True

    workflow = Workflow(name="wf", steps=[Step(name="broken", executor=broken), Verify([gate], on_fail="broken")])
    out = await _run_path(workflow, use_async, stream, input="go")
    assert out.status == RunStatus.completed
    gate_output = _verify_output(out)
    assert gate_output.steps[0].success is False
    assert "segment exploded" in gate_output.steps[0].error
    assert judged == [False]
    # The checks passed, but a failed segment still leaves the gate unsuccessful.
    assert gate_output.verification.status == "verified"
    assert gate_output.success is False


def test_unresolvable_reference_in_the_segment_still_stops_the_run():
    def unresolved(step_input: StepInput) -> StepOutput:
        raise UnresolvableCallableError("executor 'ghost' was not resolvable")

    workflow = Workflow(
        name="wf", steps=[Step(name="ghost", executor=unresolved), Verify([always_pass], on_fail="ghost")]
    )
    # A missing reference is never recorded as a failed segment output; it fails the run.
    with pytest.raises(UnresolvableCallableError):
        workflow.run(input="go")


def test_selector_returned_unresolved_verify_stops_the_run():
    writer_model = ScriptedModel([_text("draft")])
    stray = Verify([always_pass], name="stray")
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Router(
                name="router",
                selector=lambda step_input: stray,
                choices=[Step(name="other", executor=lambda step_input: StepOutput(content="other"))],
            ),
        ],
    )
    with pytest.raises(UnresolvedVerifyError):
        workflow.run(input="go")


def test_history_step_without_db_is_kept():
    ran = {"n": 0}

    def writer(step_input: StepInput) -> StepOutput:
        ran["n"] += 1
        return StepOutput(content="draft")

    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="intro", executor=lambda step_input: StepOutput(content="intro")),
            Step(name="writer", executor=writer, add_workflow_history=True),
            Verify([always_pass]),
        ],
    )
    # The default target is the history step; without a db it still runs as the segment.
    workflow.run(input="go")
    assert ran["n"] == 1


def test_mcp_tool_walk_reaches_router_routes_condition_else_branch_and_absorbed_segments():
    class MCPTools:
        """Stands in for the real MCPTools class, which the walk recognizes by name."""

    in_segment = MCPTools()
    in_route = MCPTools()
    in_list_route = MCPTools()
    in_else = MCPTools()
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="draft", agent=Agent(name="draft", tools=[in_segment])),
            Verify([always_pass], on_fail="draft", name="gate"),
            Router(
                name="router",
                selector=lambda step_input: "a",
                choices=[
                    Step(name="a", agent=Agent(name="a", tools=[in_route])),
                    [Step(name="b", agent=Agent(name="b", tools=[in_list_route])), Verify([always_pass], on_fail="b")],
                ],
            ),
            Condition(
                name="cond",
                evaluator=lambda step_input: True,
                steps=[Step(name="c", executor=lambda step_input: StepOutput(content="c"))],
                else_steps=[Step(name="d", agent=Agent(name="d", tools=[in_else]))],
            ),
        ],
    )
    # After preparation each Verify holds its absorbed segment; the walk must recurse into it.
    workflow._prepare_steps()
    assert [type(s).__name__ for s in workflow.steps] == ["Verify", "Router", "Condition"]
    found: List[Any] = []
    collect_mcp_tools_from_workflow(workflow, found)
    assert all(tool in found for tool in (in_segment, in_route, in_list_route, in_else))


# ---------------------------------------------------------------------------
# Terminal run status and answer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", ["last_word", "pure_gate", "halting", "unverified_then_step", "nested_halting", "verified"]
)
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream", [False, True])
async def test_terminal_status_and_answer(case, use_async, stream):
    """The run's status and answer come from the gate that decided the run."""
    published = {"n": 0}
    judged: List[Any] = []

    def publish(step_input: StepInput) -> StepOutput:
        published["n"] += 1
        return StepOutput(content="PUBLISHED")

    def capturing_fail(run_output):
        judged.append(run_output)
        return "never good enough"

    def halting() -> Verify:
        return Verify([always_fail], on_fail="writer", max_attempts=1, stop_on_unverified=True)

    steps: List[Any] = {
        "last_word": lambda: [_writer("draft 1", "draft 2"), Verify([always_fail], on_fail="writer", max_attempts=2)],
        "pure_gate": lambda: [_writer(), Verify([capturing_fail], on_fail=None)],
        "halting": lambda: [_writer(), halting(), Step(name="publish", executor=publish)],
        "unverified_then_step": lambda: [
            _writer(),
            Verify([always_fail], on_fail="writer", max_attempts=1),
            Step(name="publish", executor=publish),
        ],
        "nested_halting": lambda: [
            Steps(name="pipeline", steps=[_writer(), halting()]),
            Step(name="publish", executor=publish),
        ],
        "verified": lambda: [_writer(), Verify([always_pass])],
    }[case]()

    out = await _run_path(Workflow(name="wf", steps=steps), use_async, stream, input="go")
    gate = _verify_output(out)

    if case == "verified":
        assert out.status == RunStatus.completed
        assert out.verification is not None and out.verification.status == "verified"
        return
    assert out.verification is not None and out.verification.status == "unverified"
    if case == "unverified_then_step":
        assert out.status == RunStatus.completed
        assert out.content == "PUBLISHED"
        assert published["n"] == 1
        return
    assert out.status == RunStatus.unverified
    if case == "last_word":
        assert out.verification.stop_reason == "exhausted"
        assert len(out.verification.attempts) == 2
        assert out.content == "draft 2"
        assert gate.content.startswith("Verify verify: unverified (exhausted)")
    elif case == "pure_gate":
        assert out.content == "draft"
        assert gate.success is False
        assert gate.content == "draft"
        assert gate.error.startswith("Verify verify: unverified")
        assert isinstance(judged[0], RunOutput) and judged[0].content == "draft"
    else:
        assert out.content == "draft"
        assert gate.content.startswith("Verify verify: unverified")
        assert gate.stop is True
        assert published["n"] == 0


def test_agentos_run_listing_filters_on_unverified(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    workflow = Workflow(
        id="gated", name="Gated", db=db, steps=[_writer(), Verify([always_fail], on_fail="writer", max_attempts=1)]
    )
    workflow.run(input="go", session_id="s1")
    app = AgentOS(workflows=[workflow], telemetry=False).get_app()
    client = TestClient(app, raise_server_exceptions=False)

    listed = client.get("/workflows/gated/runs", params={"session_id": "s1", "status": "UNVERIFIED"})
    assert listed.status_code == 200, listed.text
    assert [run["status"] for run in listed.json()] == ["UNVERIFIED"]
    assert client.get("/workflows/gated/runs", params={"session_id": "s1", "status": "COMPLETED"}).json() == []

    # A continue on a run that ended unverified is refused with the reason.
    run_id = listed.json()[0]["run_id"]
    resp = client.post(
        f"/workflows/gated/runs/{run_id}/continue",
        data={"session_id": "s1", "stream": "false", "background": "false"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "run ended unverified"


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_verify_emits_its_own_stream_events(use_async):
    workflow = Workflow(
        name="wf",
        steps=[_writer("draft one", "draft two"), Verify([fail_once()], on_fail="writer", max_attempts=2, name="gate")],
    )
    if use_async:
        events = [event async for event in workflow.arun(input="go", stream=True, stream_events=True)]
    else:
        events = list(workflow.run(input="go", stream=True, stream_events=True))
    started = [e for e in events if isinstance(e, VerifyExecutionStartedEvent)]
    attempts_started = [e for e in events if isinstance(e, VerifyAttemptStartedEvent)]
    attempts_completed = [e for e in events if isinstance(e, VerifyAttemptCompletedEvent)]
    completed = [e for e in events if isinstance(e, VerifyExecutionCompletedEvent)]
    assert len(started) == 1 and started[0].step_name == "gate" and started[0].max_attempts == 2
    assert [e.attempt for e in attempts_started] == [1, 2]
    assert [(e.attempt, e.passed, e.should_continue) for e in attempts_completed] == [
        (1, False, True),
        (2, True, False),
    ]
    assert len(completed) == 1
    assert completed[0].status == "verified" and completed[0].total_attempts == 2
    assert completed[0].verification["stop_reason"] == "passed"
    # The events serialize and come back by type.
    revived = workflow_run_output_event_from_dict(completed[0].to_dict())
    assert isinstance(revived, VerifyExecutionCompletedEvent)


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_streamed_print_response_renders_a_verify_step(use_async):
    workflow = Workflow(name="wf", steps=[_writer(), Verify([always_fail], on_fail="writer", max_attempts=1)])
    buffer = io.StringIO()
    console = Console(file=buffer, width=120)
    if use_async:
        await workflow.aprint_response(input="go", stream=True, console=console)
    else:
        workflow.print_response(input="go", stream=True, console=console)

    text = buffer.getvalue()
    assert "draft" in text
    assert "Workflow execution failed" not in text


# ---------------------------------------------------------------------------
# An unverified agent or nested-workflow step inside a workflow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_step_nested_workflow_success(monkeypatch, use_async):
    """A nested workflow that ended unverified is not a successful step, and names why."""
    nested = WorkflowRunOutput(
        run_id="nested-run",
        content="nested answer",
        status=RunStatus.unverified,
        verification=Verification(status="unverified", stop_reason="exhausted"),
    )

    def fake_run(self, **kwargs):
        return nested

    async def fake_arun(self, **kwargs):
        return nested

    step = Step(name="outer", workflow=Workflow(name="inner", steps=[Step(name="done", executor=lambda si: "ok")]))
    if use_async:
        monkeypatch.setattr(Workflow, "arun", fake_arun)
        output = await step._aexecute_nested_workflow(step_input=StepInput(input="x"))
    else:
        monkeypatch.setattr(Workflow, "run", fake_run)
        output = step._execute_nested_workflow(step_input=StepInput(input="x"))
    assert output.success is False
    assert output.error == "Run ended unverified (exhausted)"
    assert output.content == "nested answer"


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_step_after_an_unverified_agent_step_receives_the_draft(use_async):
    received = {}

    def publish(step_input: StepInput) -> StepOutput:
        received["content"] = step_input.previous_step_content
        return StepOutput(content="published")

    writer = Agent(
        name="writer",
        model=ScriptedModel([_text("draft")]),
        verifiers=[lambda run_output: "not good enough"],
        verification=VerificationConfig(max_attempts=1),
        telemetry=False,
    )
    workflow = Workflow(name="wf", steps=[Step(name="writer", agent=writer), Step(name="publish", executor=publish)])

    out = await workflow.arun(input="go") if use_async else workflow.run(input="go")

    writer_output = out.step_results[0]
    assert writer_output.success is False
    assert writer_output.error == "Run ended unverified (exhausted)"
    assert writer_output.content == "draft"
    assert received["content"] == "draft"
