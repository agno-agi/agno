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
    assert {s.value for s in CancellationStage} == {"BEFORE_EXECUTION", "DURING_EXECUTION", "PAUSED"}
    assert CancellationStage("PAUSED") is CancellationStage.paused
    assert CancellationStage.before_execution == "BEFORE_EXECUTION", "a str enum compares to its stored value"


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
        run = cls(status=RunStatus.cancelled, cancellation_stage=CancellationStage.before_execution, **kwargs)
        wire = run.to_dict()
        assert wire["cancellation_stage"] == "BEFORE_EXECUTION"
        loaded = cls.from_dict(wire)
        assert loaded.cancellation_stage is CancellationStage.before_execution

    def test_unknown_future_value_survives_a_round_trip(self, cls, kwargs):
        """A newer server may write a stage this version does not know: it
        must load and re-serialize unchanged, never raise or be dropped."""
        wire = {**cls(status=RunStatus.cancelled, **kwargs).to_dict(), "cancellation_stage": "SOMETHING_NEW"}
        loaded = cls.from_dict(wire)
        assert loaded.cancellation_stage == "SOMETHING_NEW"
        assert loaded.to_dict()["cancellation_stage"] == "SOMETHING_NEW"


class TestMidExecutionHandlers:
    def test_agent_cancellation_handler_marks_during_execution_and_keeps_partial_output(self):
        from agno.agent._run import _handle_run_cancellation

        run = RunOutput(run_id="r1", agent_id="a1", content="partial answer", status=RunStatus.running)
        out = _handle_run_cancellation(run, RunCancelledException("stop"))
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.during_execution
        assert out.content == "partial answer", "partial output is preserved, not replaced by the reason"

    def test_team_cancellation_handler_marks_during_execution(self):
        from agno.team._run import _handle_team_run_cancellation

        run = TeamRunOutput(run_id="r1", team_id="t1", status=RunStatus.running)
        out = _handle_team_run_cancellation(run, RunCancelledException("stop"))
        assert out.status == RunStatus.cancelled
        assert out.cancellation_stage is CancellationStage.during_execution
