"""CancellationStage: a machine-readable companion to the CANCELLED status.

The same status covers a run that never started, a run stopped mid-execution
with partial output, and a run stopped while parked for a human-in-the-loop
continuation. Consumers used to tell them apart by matching the human
reason on ``content``; the stage is the field for that.
"""

import pytest

from agno.exceptions import RunCancelledException
from agno.run.agent import RunOutput
from agno.run.base import CancellationStage, RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput


def test_stage_values_are_a_wire_contract():
    assert {s.value for s in CancellationStage} == {"PENDING", "EXECUTING", "PAUSED"}
    assert CancellationStage("PAUSED") is CancellationStage.paused
    assert CancellationStage.pending == "PENDING", "a str enum compares to its stored value"


@pytest.mark.parametrize(
    "cls, kwargs",
    [
        (RunOutput, {"run_id": "r1", "agent_id": "a1"}),
        (TeamRunOutput, {"run_id": "r1", "team_id": "t1"}),
        (WorkflowRunOutput, {"run_id": "r1", "workflow_id": "w1"}),
    ],
    ids=["agent", "team", "workflow"],
)
class TestRoundTrip:
    def test_unset_stage_is_absent_from_the_wire(self, cls, kwargs):
        run = cls(status=RunStatus.cancelled, **kwargs)
        assert "cancellation_stage" not in run.to_dict(), "existing payloads must stay byte-identical"
        assert cls.from_dict(run.to_dict()).cancellation_stage is None

    def test_set_stage_serializes_as_its_value_and_loads_as_the_enum(self, cls, kwargs):
        run = cls(status=RunStatus.cancelled, cancellation_stage=CancellationStage.pending, **kwargs)
        wire = run.to_dict()
        assert wire["cancellation_stage"] == "PENDING"
        loaded = cls.from_dict(wire)
        assert loaded.cancellation_stage is CancellationStage.pending

    def test_unknown_future_value_survives_a_round_trip(self, cls, kwargs):
        """A newer server may write a stage this version does not know: it
        must load and re-serialize unchanged, never raise or be dropped."""
        wire = {**cls(status=RunStatus.cancelled, **kwargs).to_dict(), "cancellation_stage": "SOMETHING_NEW"}
        loaded = cls.from_dict(wire)
        assert loaded.cancellation_stage == "SOMETHING_NEW"
        assert loaded.to_dict()["cancellation_stage"] == "SOMETHING_NEW"


class TestMidExecutionHandlers:
    def test_agent_cancellation_handler_marks_executing_and_keeps_partial_output(self):
        from agno.agent._run import _handle_run_cancellation

        run = RunOutput(run_id="r1", agent_id="a1", content="partial answer", status=RunStatus.running)
        out = _handle_run_cancellation(run, RunCancelledException("stop"))
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.executing
        assert out.content == "partial answer", "partial output is preserved, not replaced by the reason"

    def test_team_cancellation_handler_marks_executing(self):
        from agno.team._run import _handle_team_run_cancellation

        run = TeamRunOutput(run_id="r1", team_id="t1", status=RunStatus.running)
        out = _handle_team_run_cancellation(run, RunCancelledException("stop"))
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.executing


class TestTaskLevelInterruptsStayUnknown:
    """The cores route event-loop shutdown and disconnected streaming tasks
    through the same handler as a KeyboardInterrupt. Those are neither a user
    cancel nor a never-started run, so they must not be presented as one."""

    def test_agent_handler_leaves_interrupts_unstaged(self):
        from agno.agent._run import _handle_run_cancellation

        run = RunOutput(run_id="r1", agent_id="a1", content="partial", status=RunStatus.running)
        out = _handle_run_cancellation(run, KeyboardInterrupt())
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is None

    def test_team_handler_leaves_interrupts_unstaged(self):
        from agno.team._run import _handle_team_run_cancellation

        run = TeamRunOutput(run_id="r1", team_id="t1", status=RunStatus.running)
        out = _handle_team_run_cancellation(run, KeyboardInterrupt())
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is None


class _CapturingDb:
    """A db exposing the atomic run-status primitive, recording each patch."""

    def __init__(self):
        self.patches: list = []

    async def update_run_in_session(self, session_id, run_id, fields, **kwargs):
        from agno.run.status_persist import RunPersistOutcome

        self.patches.append(dict(fields))
        return RunPersistOutcome.UPDATED


@pytest.mark.parametrize(
    "component_type, cls, kwargs",
    [
        ("agent", RunOutput, {"run_id": "r1", "agent_id": "a1"}),
        ("team", TeamRunOutput, {"run_id": "r1", "team_id": "t1"}),
        ("workflow", WorkflowRunOutput, {"run_id": "r1", "workflow_id": "w1"}),
    ],
    ids=["agent", "team", "workflow"],
)
class TestTransitionCarriesTheStage:
    """Adapters with the atomic primitive persist only the patched fields, so
    a stage set on the run object must ride the status patch; otherwise it
    reached only the whole-run fallback and Postgres stored CANCELLED with no
    stage at all."""

    @pytest.mark.asyncio
    async def test_cancelled_transition_patches_the_stage(self, component_type, cls, kwargs):
        from types import SimpleNamespace

        from agno.run.status_persist import apersist_run_transition

        db = _CapturingDb()
        run = cls(status=RunStatus.cancelled, cancellation_stage=CancellationStage.pending, **kwargs)
        await apersist_run_transition(SimpleNamespace(db=db), component_type, "s1", run)
        assert db.patches == [{"status": "CANCELLED", "cancellation_stage": "PENDING"}]

    @pytest.mark.asyncio
    async def test_cancelled_transition_without_a_stage_patches_no_key(self, component_type, cls, kwargs):
        from types import SimpleNamespace

        from agno.run.status_persist import apersist_run_transition

        db = _CapturingDb()
        await apersist_run_transition(
            SimpleNamespace(db=db), component_type, "s1", cls(status=RunStatus.cancelled, **kwargs)
        )
        assert db.patches == [{"status": "CANCELLED"}]

    @pytest.mark.asyncio
    async def test_redriving_a_cancelled_run_clears_its_stale_stage(self, component_type, cls, kwargs):
        """A cancelled run loaded from the store still carries its stage; when
        it is continued the stored row must not keep a stage that contradicts
        a non-cancelled status."""
        from types import SimpleNamespace

        from agno.run.status_persist import apersist_run_transition

        db = _CapturingDb()
        run = cls(status=RunStatus.running, cancellation_stage=CancellationStage.pending, **kwargs)
        await apersist_run_transition(SimpleNamespace(db=db), component_type, "s1", run)
        assert db.patches == [{"status": "RUNNING", "cancellation_stage": None}]
        assert run.cancellation_stage is None, "the object is cleared too, for the whole-run fallback"
