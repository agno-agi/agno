"""RunStatus.unverified across the engine-layer surfaces.

Each test pins one surface that enumerates, filters, or maps run statuses:
workflow step success derivation, workflow-session history, the eval suite's
status messages, the environments stop-reason mapping, the A2A task-state
mapping, and the telemetry payloads.
"""

import asyncio

import pytest

from agno.agent import Agent
from agno.agent._telemetry import get_telemetry_data as get_agent_telemetry_data
from agno.environments._engine import _STATUS_TO_STOP, StopReason, _AttemptState, _stop_reason_for
from agno.eval.suite import _STATUS_ERRORS
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.team import Team
from agno.team._telemetry import get_telemetry_data as get_team_telemetry_data
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# --- workflow/step.py: step success derivation ---


def _noop_executor(step_input):
    return "ok"


def test_step_executor_path_unverified_is_not_success():
    """The executor path derives success from the run status: unverified fails."""
    step = Step(name="exec-step", executor=_noop_executor)
    output = step._process_step_output(RunOutput(content="answer", status=RunStatus.unverified))
    assert output.success is False
    # The failed step carries the run's content as its error, same as error/cancelled.
    assert output.error == "answer"


def test_step_executor_path_completed_is_success():
    step = Step(name="exec-step", executor=_noop_executor)
    output = step._process_step_output(RunOutput(content="answer", status=RunStatus.completed))
    assert output.success is True
    assert output.error is None


@pytest.fixture
def nested_workflow_step():
    inner = Workflow(name="inner", steps=[Step(name="noop", executor=_noop_executor)])
    return Step(name="outer", workflow=inner)


def _nested_output(status: RunStatus) -> WorkflowRunOutput:
    return WorkflowRunOutput(run_id="nested-run", content="nested answer", status=status)


@pytest.mark.parametrize(
    "status,expected_success",
    [
        (RunStatus.unverified, False),
        (RunStatus.error, False),
        (RunStatus.completed, True),
    ],
)
def test_step_nested_workflow_sync_success(nested_workflow_step, monkeypatch, status, expected_success):
    """The sync nested-workflow path derives success from the nested run's status."""

    def fake_run(self, **kwargs):
        return _nested_output(status)

    monkeypatch.setattr(Workflow, "run", fake_run)
    output = nested_workflow_step._execute_nested_workflow(step_input=StepInput(input="x"))
    assert output.success is expected_success


@pytest.mark.parametrize(
    "status,expected_success",
    [
        (RunStatus.unverified, False),
        (RunStatus.error, False),
        (RunStatus.completed, True),
    ],
)
def test_step_nested_workflow_async_success(nested_workflow_step, monkeypatch, status, expected_success):
    """The async nested-workflow path mirrors the sync derivation."""

    async def fake_arun(self, **kwargs):
        return _nested_output(status)

    monkeypatch.setattr(Workflow, "arun", fake_arun)
    output = asyncio.run(nested_workflow_step._aexecute_nested_workflow(step_input=StepInput(input="x")))
    assert output.success is expected_success


# --- session/workflow.py: workflow history filter ---


def test_workflow_history_includes_unverified_runs():
    """History is an include-list: completed and unverified runs both carry a real
    transcript; error/cancelled/paused runs stay excluded."""
    session = WorkflowSession(
        session_id="session-1",
        runs=[
            WorkflowRunOutput(input="q1", content="a1", status=RunStatus.completed),
            WorkflowRunOutput(input="q2", content="a2", status=RunStatus.unverified),
            WorkflowRunOutput(input="q3", content="a3", status=RunStatus.error),
            WorkflowRunOutput(input="q4", content="a4", status=RunStatus.cancelled),
        ],
    )
    assert session.get_workflow_history() == [("q1", "a1"), ("q2", "a2")]


def test_workflow_history_num_runs_counts_unverified():
    """num_runs slices the filtered list, so an unverified run occupies a slot."""
    session = WorkflowSession(
        session_id="session-1",
        runs=[
            WorkflowRunOutput(input="q1", content="a1", status=RunStatus.completed),
            WorkflowRunOutput(input="q2", content="a2", status=RunStatus.unverified),
        ],
    )
    assert session.get_workflow_history(num_runs=1) == [("q2", "a2")]


# --- eval/suite.py: non-gradeable status messages ---


def test_eval_suite_status_errors_cover_unverified():
    """The suite reports unverified with its own message instead of the generic
    fallback; the gradeable gate itself is completed-only, so unverified runs are
    already non-gradeable by derivation."""
    assert RunStatus.unverified in _STATUS_ERRORS
    message = _STATUS_ERRORS[RunStatus.unverified]
    assert "unverified" in message
    # Distinct from the error-status message: an unverified run did not error.
    assert message != _STATUS_ERRORS[RunStatus.error]


# --- environments/_engine.py: stop-reason mapping ---


def test_environments_status_to_stop_maps_unverified():
    assert _STATUS_TO_STOP[RunStatus.unverified] == "unverified"
    assert StopReason.unverified.value == "unverified"


def test_environments_stop_reason_for_unverified_run():
    state = _AttemptState(run=RunOutput(content="a", status=RunStatus.unverified))
    reason = _stop_reason_for(state)
    assert reason == StopReason.unverified
    # Not folded into error: the uniform-error-storm abort keys on StopReason.error
    # and must not trip on runs that merely failed verification.
    assert reason != StopReason.error
    # Not completed: the scoring gate is completed-only, so the attempt stays unscored.
    assert reason != StopReason.completed


# --- os/interfaces/a2a/utils.py: task-state mapping ---


def test_a2a_maps_unverified_to_failed():
    pytest.importorskip("a2a")
    from a2a.types import TaskState

    from agno.os.interfaces.a2a.utils import _map_run_status_to_task_state

    assert _map_run_status_to_task_state(RunStatus.unverified) == TaskState.failed
    # The mapping default launders unknown statuses to completed; the explicit
    # entry above is what keeps unverified out of that default.
    assert _map_run_status_to_task_state(RunStatus.completed) == TaskState.completed


# --- telemetry: has_verifiers ---


def test_agent_telemetry_reports_has_verifiers():
    plain = Agent(name="plain")
    verified = Agent(name="verified", verifiers=[lambda run_output: True])
    assert get_agent_telemetry_data(plain)["has_verifiers"] is False
    assert get_agent_telemetry_data(verified)["has_verifiers"] is True


def test_team_telemetry_reports_has_verifiers():
    team = Team(name="team", members=[Agent(name="member")])
    data = get_team_telemetry_data(team)
    assert data["has_verifiers"] is False


def test_team_telemetry_reports_has_verifiers_true_with_verifiers():
    team = Team(name="team", members=[Agent(name="member")], verifiers=[lambda run_output: True])
    assert get_team_telemetry_data(team)["has_verifiers"] is True
