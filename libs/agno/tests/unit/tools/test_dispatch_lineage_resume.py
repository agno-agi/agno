"""The dispatch guard's state must survive a HITL pause.

The dispatch lineage and hop counter ride RunContext.metadata and are
persisted on the run row. A resume that rebuilds metadata from caller input
presents a genuinely nested run as top-level: the cycle guard and the depth
cap read an empty lineage, and one human approval per hop re-opens the
runaway the guard exists to refuse. The resume path is the fifth seam where
the runtime-owned keys must win over caller input.
"""

import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.db.schemas.scheduler import (
    DISPATCH_CHAIN_METADATA_KEY,
    DISPATCH_DEPTH_METADATA_KEY,
)
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunContext
from agno.run.requirement import RunRequirement
from agno.team import Team
from agno.tools import tool
from agno.tools.studio_runner import StudioRunnerTools
from agno.workflow import Step, Workflow
from agno.workflow.types import HumanReview, StepInput, StepOutput

_CHAIN = DISPATCH_CHAIN_METADATA_KEY
_DEPTH = DISPATCH_DEPTH_METADATA_KEY


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        from agno.metrics import MessageMetrics

        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        r.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return r

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


_CAPTURED: List[Optional[Dict[str, Any]]] = []


@tool(requires_confirmation=True)
def gated_probe(run_context: Optional[RunContext] = None) -> str:
    """A confirmation-gated tool that records the metadata of the run it
    finally executes on -- which, after a pause, is the CONTINUED run."""
    metadata = getattr(run_context, "metadata", None)
    _CAPTURED.append(dict(metadata) if isinstance(metadata, dict) else None)
    return "probed"


class _StubTeam:
    def __init__(self, team_id: str = "a"):
        self.id = team_id
        self.name = team_id.upper()
        self.seen: Optional[Dict[str, Any]] = None
        self.seen_metadata: Optional[Dict[str, Any]] = None

    def run(self, message, stream=None, user_id=None, session_id=None, metadata=None, run_id=None):
        self.seen = {"message": message}
        self.seen_metadata = metadata
        return type("Out", (), {"run_id": "r", "session_id": "s", "status": "COMPLETED", "content": "sub-done"})()

    async def arun(self, message, stream=None, user_id=None, session_id=None, metadata=None, run_id=None):
        return self.run(message, stream=stream, user_id=user_id, session_id=session_id, metadata=metadata)

    def deep_copy(self):
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


class _StubAgent(_StubTeam):
    def __init__(self, agent_id: str = "solo"):
        super().__init__(agent_id)


def _confirmed(requirements) -> List[RunRequirement]:
    """Round-trip requirements through their wire format and confirm them,
    the way a frontend or a fresh process would send them back."""
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        req.confirm()
        confirmed.append(req)
    return confirmed


def _probe_component(kind: str, db: SqliteDb, extra_tools: Optional[List[Any]] = None, script: Optional[List] = None):
    """An agent or team whose first turn pauses on the gated probe."""
    script = script or [("tool", "gated_probe", {}, "tc-probe"), ("content", "done")]
    model = _ScriptedModel(f"m-{kind}", script)
    tools: List[Any] = [gated_probe, *(extra_tools or [])]
    if kind == "agent":
        return Agent(id="prober", name="Prober", model=model, tools=tools, db=db, telemetry=False)
    member = Agent(id="bystander", name="Bystander", model=_ScriptedModel("m-member", [("content", "hi")]))
    return Team(id="prober", name="Prober", model=model, members=[member], tools=tools, db=db, telemetry=False)


_DISPATCHED = {_CHAIN: ["team:outer"], _DEPTH: 1, "tenant": "acme"}


async def _pause_then_resume(component, kind: str, use_async: bool, run_metadata, resume_kwargs=None):
    run1 = component.run("go", session_id=f"s-{kind}", metadata=dict(run_metadata) if run_metadata else None)
    assert run1.is_paused, "the gated probe should pause the first run"
    kwargs = dict(
        run_id=run1.run_id,
        session_id=f"s-{kind}",
        requirements=_confirmed(run1.requirements),
        **(resume_kwargs or {}),
    )
    if use_async:
        return await component.acontinue_run(**kwargs)
    return component.continue_run(**kwargs)


class TestDispatchLineageSurvivesContinue:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["agent", "team"])
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    async def test_dispatch_lineage_survives_continue(self, tmp_path, kind, use_async):
        _CAPTURED.clear()
        db = SqliteDb(db_file=str(tmp_path / "resume.db"))
        component = _probe_component(kind, db)

        run2 = await _pause_then_resume(component, kind, use_async, _DISPATCHED)
        assert run2.status.value == "COMPLETED"
        assert len(_CAPTURED) == 1
        captured = _CAPTURED[0] or {}
        assert captured.get(_CHAIN) == ["team:outer"]
        assert captured.get(_DEPTH) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["agent", "team"])
    async def test_caller_cannot_override_restored_lineage(self, tmp_path, kind):
        _CAPTURED.clear()
        db = SqliteDb(db_file=str(tmp_path / "override.db"))
        component = _probe_component(kind, db)

        forged = {_CHAIN: ["team:forged"], _DEPTH: 0, "note": "kept"}
        run2 = await _pause_then_resume(component, kind, False, _DISPATCHED, resume_kwargs={"metadata": forged})
        assert run2.status.value == "COMPLETED"
        captured = (_CAPTURED or [None])[0] or {}
        # The stored reserved keys win; the caller's other metadata may ride.
        assert captured.get(_CHAIN) == ["team:outer"]
        assert captured.get(_DEPTH) == 1
        assert captured.get("note") == "kept"


def _dispatching_component(kind: str, db: SqliteDb, stubs: List[Any], self_dispatch: str, target_id: str):
    """Pauses on the gated probe, then (post-resume) dispatches ``target_id``."""
    runner = StudioRunnerTools(
        include_teams=[s for s in stubs if isinstance(s, _StubTeam) and not isinstance(s, _StubAgent)] or None,
        include_agents=[s for s in stubs if isinstance(s, _StubAgent)] or None,
        self_dispatch=self_dispatch,
    )  # type: ignore[arg-type]
    run_tool = "run_agent" if any(isinstance(s, _StubAgent) for s in stubs) else "run_team"
    arg = "agent_id" if run_tool == "run_agent" else "team_id"
    script = [
        ("tool", "gated_probe", {}, "tc-probe"),
        ("tool", run_tool, {arg: target_id, "message": "go deeper"}, "tc-dispatch"),
        ("content", "finished"),
    ]
    return _probe_component(kind, db, extra_tools=[runner], script=script)


class TestGuardHoldsAcrossAPause:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["never", "once"])
    @pytest.mark.parametrize("kind,use_async", [("agent", False), ("agent", True), ("team", False)])
    async def test_cycle_guard_holds_across_a_pause(self, tmp_path, mode, kind, use_async):
        # The run was dispatched by team 'a' (it is on the inherited lineage);
        # after pause+resume it dispatches 'a' back. A -> B -> A must stay
        # refused -- in BOTH modes: this is inherited-lineage blocking, which
        # "once" does not exempt.
        _CAPTURED.clear()
        db = SqliteDb(db_file=str(tmp_path / "cycle.db"))
        a = _StubTeam("a")
        component = _dispatching_component(kind, db, [a], mode, target_id="a")

        nested = {_CHAIN: ["team:a", f"{kind}:prober"], _DEPTH: 1}
        run2 = await _pause_then_resume(component, kind, use_async, nested)
        assert run2.status.value == "COMPLETED"
        assert a.seen is None, "the resumed run re-entered its own dispatcher"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind,use_async", [("agent", False), ("team", True)])
    async def test_depth_cap_holds_across_a_pause(self, tmp_path, kind, use_async):
        # At the default cap (2), a run that inherited depth 2 may not
        # dispatch at all -- including after a pause.
        _CAPTURED.clear()
        db = SqliteDb(db_file=str(tmp_path / "depth.db"))
        c = _StubTeam("c")
        component = _dispatching_component(kind, db, [c], "never", target_id="c")

        at_cap = {_CHAIN: ["team:x", "team:y"], _DEPTH: 2}
        run2 = await _pause_then_resume(component, kind, use_async, at_cap)
        assert run2.status.value == "COMPLETED"
        assert c.seen is None, "the resumed run dispatched past the depth cap"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    async def test_self_dispatch_once_is_still_once_across_a_pause(self, tmp_path, use_async):
        # This run IS the one self-run "once" permits (its own token is on the
        # inherited lineage). Pausing and resuming must not recharge the
        # exemption into a second self-run.
        _CAPTURED.clear()
        db = SqliteDb(db_file=str(tmp_path / "once.db"))
        solo = _StubAgent("prober")
        component = _dispatching_component("agent", db, [solo], "once", target_id="prober")

        self_run = {_CHAIN: ["agent:prober"], _DEPTH: 1}
        run2 = await _pause_then_resume(component, "agent", use_async, self_run)
        assert run2.status.value == "COMPLETED"
        assert solo.seen is None, "'once' recharged across a pause"


def _capture_metadata(step_input: StepInput, run_context: Optional[RunContext] = None) -> StepOutput:
    """A workflow step that records the metadata its run carries."""
    metadata = getattr(run_context, "metadata", None)
    _CAPTURED.append(dict(metadata) if isinstance(metadata, dict) else None)
    return StepOutput(content="captured")


def _write_metadata(step_input: StepInput, run_context: Optional[RunContext] = None) -> StepOutput:
    """A workflow step that writes to the metadata of its run."""
    assert run_context is not None and run_context.metadata is not None
    run_context.metadata["written_by_step"] = True
    return StepOutput(content="written")


@tool
def read_metadata(run_context: Optional[RunContext] = None) -> str:
    """Records the metadata of the step agent's run."""
    metadata = getattr(run_context, "metadata", None)
    _CAPTURED.append(dict(metadata) if isinstance(metadata, dict) else None)
    return "read"


async def _pause_then_resume_workflow(workflow: Workflow, use_async: bool, stream: bool, run_metadata):
    """Pause on the step's confirmation, then continue from storage the way a later request does."""
    run1 = workflow.run("go", session_id="s-wf", metadata=dict(run_metadata) if run_metadata else None)
    assert run1.is_paused, "the confirmation should pause the workflow before its step"
    for requirement in run1.step_requirements or []:
        requirement.confirm()
    kwargs: Dict[str, Any] = dict(run_id=run1.run_id, session_id="s-wf", step_requirements=run1.step_requirements)
    if stream and use_async:
        async for _ in await workflow.acontinue_run(stream=True, **kwargs):
            pass
    elif stream:
        for _ in workflow.continue_run(stream=True, **kwargs):
            pass
    elif use_async:
        await workflow.acontinue_run(**kwargs)
    else:
        workflow.continue_run(**kwargs)
    run2 = workflow.get_run_output(run_id=run1.run_id, session_id="s-wf")
    assert run2 is not None
    return run2


class TestWorkflowLineageSurvivesContinue:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    @pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
    async def test_dispatch_lineage_reaches_the_steps_of_a_continued_workflow(self, tmp_path, use_async, stream):
        _CAPTURED.clear()
        db = SqliteDb(db_file=str(tmp_path / "wf-resume.db"))
        step = Step(name="gated", executor=_capture_metadata, human_review=HumanReview(requires_confirmation=True))
        workflow = Workflow(id="wf", name="WF", db=db, steps=[step], telemetry=False)

        run2 = await _pause_then_resume_workflow(workflow, use_async, stream, _DISPATCHED)
        assert run2.status.value == "COMPLETED"
        # The lineage, and the caller's own metadata with it.
        assert _CAPTURED == [_DISPATCHED]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    @pytest.mark.parametrize(
        "workflow_metadata,run_metadata,expected",
        [
            ({"owner": "wf"}, _DISPATCHED, {"owner": "wf", **_DISPATCHED}),
            ({"owner": "wf"}, {"tenant": "acme"}, {"owner": "wf", "tenant": "acme"}),
            # A fresh run hands its steps an empty dict when nothing sets metadata, so the step
            # agent's own metadata is applied in neither run.
            (None, None, {}),
        ],
        ids=["dispatched", "top-level", "no-metadata"],
    )
    async def test_a_continued_step_sees_the_metadata_a_fresh_step_sees(
        self, tmp_path, use_async, workflow_metadata, run_metadata, expected
    ):
        # A step agent takes its own metadata only when the run carries none, so a continued run
        # that carried part of the stored metadata would change what its tools and hooks read.
        def workflow(name: str, review: Optional[HumanReview]) -> Workflow:
            script = [("tool", "read_metadata", {}, "tc-read"), ("content", "finished")]
            agent = Agent(
                id="stepper",
                model=_ScriptedModel("m-step", script),
                tools=[read_metadata],
                metadata={"agent_default": "x"},
                telemetry=False,
            )
            db = SqliteDb(db_file=str(tmp_path / f"{name}.db"))
            step = Step(name="read", agent=agent, human_review=review)
            return Workflow(id="wf", name="WF", db=db, steps=[step], metadata=workflow_metadata, telemetry=False)

        _CAPTURED.clear()
        fresh = workflow("fresh", None).run("go", session_id="s-wf", metadata=run_metadata and dict(run_metadata))
        assert fresh.status.value == "COMPLETED"
        paused = workflow("paused", HumanReview(requires_confirmation=True))
        run2 = await _pause_then_resume_workflow(paused, use_async, False, run_metadata)
        assert run2.status.value == "COMPLETED"

        assert _CAPTURED == [expected, expected]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    async def test_a_step_metadata_write_on_a_continued_leg_reaches_the_stored_run(self, tmp_path, use_async):
        # The run context and the stored run share one metadata dict on a fresh run, so a step's
        # write is stored with the run. A continued leg has to keep that link.
        def workflow(name: str, review: Optional[HumanReview]) -> Workflow:
            db = SqliteDb(db_file=str(tmp_path / f"{name}.db"))
            step = Step(name="write", executor=_write_metadata, human_review=review)
            return Workflow(id="wf", name="WF", db=db, steps=[step], telemetry=False)

        fresh = workflow("fresh", None)
        fresh.run("go", session_id="s-wf", metadata={"tenant": "acme"})
        stored = fresh.get_session(session_id="s-wf").runs[-1]
        assert stored.metadata == {"tenant": "acme", "written_by_step": True}

        paused = workflow("paused", HumanReview(requires_confirmation=True))
        run2 = await _pause_then_resume_workflow(paused, use_async, False, {"tenant": "acme"})
        assert run2.status.value == "COMPLETED"
        assert run2.metadata == {"tenant": "acme", "written_by_step": True}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["never", "once"])
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    @pytest.mark.parametrize("stream", [False, True], ids=["run", "stream"])
    async def test_cycle_guard_holds_across_a_workflow_pause(self, tmp_path, mode, use_async, stream):
        # Team 'a' dispatched this workflow. After the pause its step dispatches 'a' back:
        # A -> workflow -> A must stay refused.
        db = SqliteDb(db_file=str(tmp_path / "wf-cycle.db"))
        a = _StubTeam("a")
        runner = StudioRunnerTools(include_teams=[a], self_dispatch=mode)  # type: ignore[arg-type]
        script = [
            ("tool", "run_team", {"team_id": "a", "message": "go deeper"}, "tc-dispatch"),
            ("content", "finished"),
        ]
        agent = Agent(id="stepper", model=_ScriptedModel("m-step", script), tools=[runner], telemetry=False)
        step = Step(name="gated", agent=agent, human_review=HumanReview(requires_confirmation=True))
        workflow = Workflow(id="wf", name="WF", db=db, steps=[step], telemetry=False)

        nested = {_CHAIN: ["team:a", "workflow:wf"], _DEPTH: 1}
        run2 = await _pause_then_resume_workflow(workflow, use_async, stream, nested)
        assert run2.status.value == "COMPLETED"
        assert a.seen is None, "the continued workflow re-entered its own dispatcher"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
    async def test_depth_cap_holds_across_a_workflow_pause(self, tmp_path, use_async):
        db = SqliteDb(db_file=str(tmp_path / "wf-depth.db"))
        c = _StubTeam("c")
        runner = StudioRunnerTools(include_teams=[c])  # type: ignore[arg-type]
        script = [
            ("tool", "run_team", {"team_id": "c", "message": "go deeper"}, "tc-dispatch"),
            ("content", "finished"),
        ]
        agent = Agent(id="stepper", model=_ScriptedModel("m-step", script), tools=[runner], telemetry=False)
        step = Step(name="gated", agent=agent, human_review=HumanReview(requires_confirmation=True))
        workflow = Workflow(id="wf", name="WF", db=db, steps=[step], telemetry=False)

        at_cap = {_CHAIN: ["team:x", "team:y"], _DEPTH: 2}
        run2 = await _pause_then_resume_workflow(workflow, use_async, False, at_cap)
        assert run2.status.value == "COMPLETED"
        assert c.seen is None, "the continued workflow dispatched past the depth cap"
