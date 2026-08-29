"""The Verify workflow step, driven through real Workflows on a scripted offline model.

Covers pass-through, loop-back with the evidence report, budget exhaustion, the pure
gate, fatal checks, advisory visibility, the async twin, both streaming paths, and
construction-time errors.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.registry import Registry
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.tools import tool
from agno.verifiers import check
from agno.workflow import Loop, Parallel, Router, Step, Verify, Workflow
from agno.workflow.types import HumanReview, StepInput, StepOutput


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


def test_pure_gate_reuse_across_workflows_raises():
    gate = Verify([always_pass], on_fail=None, name="gate")
    model_a = ScriptedModel([_text("a")])
    model_b = ScriptedModel([_text("b")])
    wf_a = Workflow(name="wf_a", steps=[Step(name="writer", agent=Agent(name="writer", model=model_a)), gate])
    wf_b = Workflow(name="wf_b", steps=[Step(name="writer", agent=Agent(name="writer", model=model_b)), gate])
    assert wf_a.run(input="go").status == RunStatus.completed
    with pytest.raises(ValueError, match="already bound to another workflow"):
        wf_b.run(input="go")


# ---------------------------------------------------------------------------
# Pure-gate content forwarding
# ---------------------------------------------------------------------------


def test_pure_gate_after_loop_forwards_real_content():
    seen = {}

    def loop_body(step_input: StepInput) -> StepOutput:
        return StepOutput(content="REAL LOOP CONTENT")

    def printer(step_input: StepInput) -> StepOutput:
        seen["content"] = step_input.previous_step_content
        return StepOutput(content="printer done")

    workflow = Workflow(
        name="wf",
        steps=[
            Loop(name="loop", steps=[Step(name="body", executor=loop_body)], max_iterations=1),
            Verify([always_pass], on_fail=None, name="gate"),
            Step(name="printer", executor=printer),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    gate_output = next(so for so in out.step_results if so.step_name == "gate")
    # The gate forwards the loop's real work, not the composite's summary line.
    assert gate_output.content == "REAL LOOP CONTENT"
    assert seen["content"] == "REAL LOOP CONTENT"


# ---------------------------------------------------------------------------
# Router choices
# ---------------------------------------------------------------------------


def test_router_direct_verify_choice_with_on_fail_raises_at_build():
    with pytest.raises(ValueError, match="pure gate"):
        Router(
            name="router",
            selector=lambda step_input: "checked",
            choices=[Verify([always_pass], name="checked")],
        )


def test_router_choices_swapped_to_bad_verify_raises_loudly_at_prepare():
    # Choices replaced after construction dodge the constructor guard; the router's own
    # step preparation must still refuse them with a raise that fails the run, instead of
    # the old mid-run explosion recorded as a completed run.
    writer_model = ScriptedModel([_text("draft")])
    router = Router(
        name="router",
        selector=lambda step_input: "checked",
        choices=[Step(name="other", executor=lambda step_input: StepOutput(content="other"))],
    )
    router.choices = [Verify([always_pass], name="checked")]
    workflow = Workflow(
        name="wf",
        steps=[Step(name="writer", agent=Agent(name="writer", model=writer_model)), router],
    )
    with pytest.raises(ValueError, match="pure gate"):
        workflow.run(input="go")


def test_router_direct_pure_gate_choice_passes():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Router(
                name="router",
                selector=lambda step_input: "gate",
                choices=[Verify([always_pass], on_fail=None, name="gate")],
            ),
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
                        Verify([always_fail], on_fail="fix", max_rounds=1, name="checked"),
                    ]
                ],
            ),
        ],
    )
    out_first = workflow.run(input="go")
    assert out_first.status == RunStatus.completed
    # Initial attempt plus one loop-back round: the segment ran exactly twice.
    first_run_executions = ran["fix"]
    assert first_run_executions == 2
    out_second = workflow.run(input="go")
    assert out_second.status == RunStatus.completed
    # The second run executes the segment once per round, exactly like the first.
    assert ran["fix"] - first_run_executions == first_run_executions


def test_router_list_route_with_verify_loop_back_stays_valid():
    ran = {"fix": 0}

    def fix(step_input: StepInput) -> StepOutput:
        ran["fix"] += 1
        return StepOutput(content="fixed")

    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="intro", executor=lambda step_input: StepOutput(content="intro")),
            Router(
                name="router",
                selector=lambda step_input: "steps_group_0",
                choices=[[Step(name="fix", executor=fix), Verify([always_pass], on_fail="fix", name="checked")]],
            ),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    assert ran["fix"] == 1


# ---------------------------------------------------------------------------
# Parallel branches
# ---------------------------------------------------------------------------


def test_parallel_direct_verify_with_on_fail_raises_at_build():
    # A branch raise at execution time is absorbed by the parallel aggregation and the
    # run completes with zero checks executed, so the refusal must land at build time.
    with pytest.raises(ValueError, match="pure gate"):
        Parallel(
            Step(name="side", executor=lambda step_input: StepOutput(content="side")),
            Verify([always_pass], name="checked"),
            name="par",
        )


def test_parallel_steps_swapped_to_bad_verify_raises_loudly_at_prepare():
    # Steps replaced after construction dodge the constructor guard; the parallel's own
    # step preparation must still refuse them with a raise that fails the run.
    writer_model = ScriptedModel([_text("draft")])
    parallel = Parallel(Step(name="other", executor=lambda step_input: StepOutput(content="other")), name="par")
    parallel.steps = [Verify([always_pass], name="checked")]
    workflow = Workflow(
        name="wf",
        steps=[Step(name="writer", agent=Agent(name="writer", model=writer_model)), parallel],
    )
    with pytest.raises(ValueError, match="pure gate"):
        workflow.run(input="go")


def test_parallel_pure_gate_still_valid():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Parallel(
                Step(name="side", executor=lambda step_input: StepOutput(content="side")),
                Verify([always_pass], on_fail=None, name="gate"),
                name="par",
            ),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    assert writer_model.calls == 1


# ---------------------------------------------------------------------------
# Structural walks over a resolved Verify
# ---------------------------------------------------------------------------


def _resolved_segment_workflow(agent: Agent, workflow_id: Optional[str] = None) -> Workflow:
    """A workflow whose Verify has already absorbed its segment, as after one prepare."""
    from agno.workflow.verify import resolve_verify_steps

    workflow = Workflow(
        id=workflow_id,
        name="wf",
        steps=[Step(name="writer", agent=agent), Verify([always_pass], on_fail="writer")],
    )
    workflow.steps = resolve_verify_steps(workflow.steps, owner=workflow)
    assert [type(s).__name__ for s in workflow.steps] == ["Verify"]
    return workflow


def test_studio_version_pin_walk_sees_absorbed_segment_agent(tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.tools.studio import StudioTools

    db = SqliteDb(db_file=str(tmp_path / "pins.db"))
    Agent(id="seg-agent", name="Seg").save(db=db)
    workflow = _resolved_segment_workflow(Agent(id="seg-agent", name="Seg"), workflow_id="wf-pins")

    studio = StudioTools(registry=Registry(dbs=[db]), db=db)
    links = studio._links_for_component(workflow) or []
    assert any(
        link.get("link_kind") == "step_agent" and link.get("child_component_id") == "seg-agent" for link in links
    )


def test_step_occurrences_walk_sees_absorbed_segment_agent():
    from agno.tools.studio_runner import StudioRunnerTools

    workflow = _resolved_segment_workflow(Agent(id="seg-agent", name="Seg"))
    occurrences = StudioRunnerTools._step_occurrences(workflow)
    assert any(kind == "step_agent" and ref_id == "seg-agent" for kind, _key, _ref_type, ref_id, _obj in occurrences)


def gate_check(run_output):
    return True


def test_component_collection_registers_check_inside_router_list_route():
    from agno.os.utils import collect_components_from_workflow

    def fix(step_input: StepInput) -> StepOutput:
        return StepOutput(content="fixed")

    workflow = Workflow(
        name="wf",
        steps=[
            Router(
                name="router",
                selector=lambda step_input: "steps_group_0",
                choices=[[Step(name="fix", executor=fix), Verify([gate_check], on_fail="fix", name="checked")]],
            ),
        ],
    )
    registry = Registry()
    collect_components_from_workflow(workflow, registry, set())
    # The check inside the list route registers by name; without it, rehydration
    # degrades the gate to a fail-closed placeholder.
    assert registry.get_function("gate_check") is gate_check


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def advisory(run_output):
    return "style could be tighter"


def gatekeeper(run_output):
    return True


def test_serialization_round_trip_preserves_per_check_policy():
    original = Verify(
        [check(advisory, required=False, rerun=2), check(gatekeeper, fatal=True)],
        on_fail=None,
        max_rounds=3,
        stop_when_unverified=True,
        name="rt",
    )
    data = original.to_dict()
    assert data["verifiers"] == [
        {"name": "advisory", "required": False, "rerun": 2, "fatal": False},
        {"name": "gatekeeper", "required": True, "rerun": 0, "fatal": True},
    ]
    registry = Registry(functions=[advisory, gatekeeper])
    restored = Verify.from_dict(data, registry=registry)
    assert restored.max_rounds == 3
    assert restored.stop_when_unverified is True
    advisory_wrapper, gatekeeper_wrapper = restored._verifiers
    assert advisory_wrapper.required is False
    assert advisory_wrapper.rerun == 2
    assert advisory_wrapper.fatal is False
    assert gatekeeper_wrapper.required is True
    assert gatekeeper_wrapper.fatal is True

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


def test_from_dict_tolerates_plain_string_verifier_entries():
    data = {
        "type": "Verify",
        "name": "legacy",
        "verifiers": ["advisory"],
        "on_fail": None,
        "max_rounds": 1,
    }
    restored = Verify.from_dict(data, registry=Registry(functions=[advisory]))
    assert restored._verifiers[0].name == "advisory"
    assert restored._verifiers[0].required is True
    assert restored._verifiers[0].rerun == 0
    assert restored._verifiers[0].fatal is False


def test_from_dict_degrades_stop_on_noop_with_warning(caplog):
    class Fingerprint:
        def capture(self):
            return "state"

    original = Verify([check(gatekeeper)], on_fail=None, stop_on_noop=True, fingerprint=Fingerprint(), name="noopy")
    data = original.to_dict()
    assert data["stop_on_noop"] is True
    with caplog.at_level("WARNING", logger="agno"):
        restored = Verify.from_dict(data, registry=Registry(functions=[gatekeeper]))
    assert restored.stop_on_noop is False
    assert any("stop_on_noop" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Step-level policy absorption
# ---------------------------------------------------------------------------


def test_absorbed_step_with_step_level_human_review_raises_at_build():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(
                name="writer",
                agent=Agent(name="writer", model=writer_model),
                human_review=HumanReview(requires_confirmation=True),
            ),
            Verify([always_pass], on_fail="writer"),
        ],
    )
    with pytest.raises(ValueError, match="cannot absorb"):
        workflow.run(input="go")
    assert writer_model.calls == 0


def test_absorbed_step_with_explicit_on_error_raises_at_build():
    writer_model = ScriptedModel([_text("draft")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(
                name="writer",
                agent=Agent(name="writer", model=writer_model),
                human_review=HumanReview(on_error="pause"),
            ),
            Verify([always_pass], on_fail="writer"),
        ],
    )
    with pytest.raises(ValueError, match="cannot absorb"):
        workflow.run(input="go")
    assert writer_model.calls == 0


def _tool_call(name: str, call_id: str) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps({})},
            }
        ],
    )


def test_tool_level_confirmation_still_pauses_through_verify():
    tool_calls = {"n": 0}

    @tool(requires_confirmation=True)
    def deploy() -> str:
        """Deploy the thing."""
        tool_calls["n"] += 1
        return "deployed"

    agent = Agent(name="deployer", model=ScriptedModel([_tool_call("deploy", "c1"), _text("done")]), tools=[deploy])
    workflow = Workflow(
        name="wf",
        steps=[Step(name="deployer", agent=agent), Verify([always_pass], on_fail="deployer", max_rounds=1)],
    )
    # Tool-level confirmation is not a step-level policy: the build must accept it and
    # the executor's pause must propagate out through the composite.
    out = workflow.run(input="go")
    assert out.is_paused is True
    assert tool_calls["n"] == 0


# ---------------------------------------------------------------------------
# stop_when_unverified
# ---------------------------------------------------------------------------


def _halting_workflow():
    writer_model = ScriptedModel([_text("draft")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_fail], on_fail="writer", max_rounds=1, stop_when_unverified=True),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    return workflow, publisher_model


def test_stop_when_unverified_halts_downstream():
    workflow, publisher_model = _halting_workflow()
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    verify_output = _verify_output(out)
    assert verify_output.success is False
    assert verify_output.stop is True
    assert publisher_model.calls == 0


def test_stop_when_unverified_halts_downstream_on_all_paths():
    workflow, publisher_model = _halting_workflow()
    list(workflow.run(input="go", stream=True))
    assert publisher_model.calls == 0

    workflow, publisher_model = _halting_workflow()
    asyncio.run(workflow.arun(input="go"))
    assert publisher_model.calls == 0

    async def collect(target: Workflow) -> None:
        async for _ in target.arun(input="go", stream=True):
            pass

    workflow, publisher_model = _halting_workflow()
    asyncio.run(collect(workflow))
    assert publisher_model.calls == 0


def test_unverified_without_stop_continues():
    writer_model = ScriptedModel([_text("draft")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_fail], on_fail="writer", max_rounds=1),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    out = workflow.run(input="go")
    assert out.status == RunStatus.completed
    verify_output = _verify_output(out)
    assert verify_output.success is False
    assert verify_output.stop is False
    assert publisher_model.calls == 1


def test_stop_when_unverified_does_not_stop_a_verified_run():
    writer_model = ScriptedModel([_text("draft")])
    publisher_model = ScriptedModel([_text("published")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_pass], stop_when_unverified=True),
            Step(name="publisher", agent=Agent(name="publisher", model=publisher_model)),
        ],
    )
    out = workflow.run(input="go")
    verify_output = _verify_output(out)
    assert verify_output.success is True
    assert verify_output.stop is False
    assert publisher_model.calls == 1


# ---------------------------------------------------------------------------
# Fingerprint settle timing
# ---------------------------------------------------------------------------


class CountingFingerprint:
    def __init__(self) -> None:
        self.captures = 0

    def capture(self) -> str:
        self.captures += 1
        return "state"


def _fingerprinted_workflow(fingerprint: CountingFingerprint) -> Workflow:
    writer_model = ScriptedModel([_text("draft")])
    return Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([always_pass], on_fail="writer", fingerprint=fingerprint),
        ],
    )


def test_fingerprint_settles_only_on_reenter_all_paths():
    # A run that passes on the first attempt needs exactly two captures: the baseline and
    # the attempt's own; a settle after the terminal round would be pure waste.
    fingerprint = CountingFingerprint()
    _fingerprinted_workflow(fingerprint).run(input="go")
    assert fingerprint.captures == 2

    fingerprint = CountingFingerprint()
    list(_fingerprinted_workflow(fingerprint).run(input="go", stream=True))
    assert fingerprint.captures == 2

    fingerprint = CountingFingerprint()
    asyncio.run(_fingerprinted_workflow(fingerprint).arun(input="go"))
    assert fingerprint.captures == 2

    async def collect(workflow: Workflow) -> None:
        async for _ in workflow.arun(input="go", stream=True):
            pass

    fingerprint = CountingFingerprint()
    asyncio.run(collect(_fingerprinted_workflow(fingerprint)))
    assert fingerprint.captures == 2


def test_fingerprint_settles_between_rounds_on_reenter():
    # A failed round that re-enters still settles, so the next round's noop comparison
    # baselines after the checks: baseline, attempt one, settle, attempt two.
    fingerprint = CountingFingerprint()
    writer_model = ScriptedModel([_text("draft one"), _text("draft two")])
    workflow = Workflow(
        name="wf",
        steps=[
            Step(name="writer", agent=Agent(name="writer", model=writer_model)),
            Verify([fail_until(2)], on_fail="writer", max_rounds=2, fingerprint=fingerprint),
        ],
    )
    out = workflow.run(input="go")
    assert _verify_output(out).success is True
    assert fingerprint.captures == 4
