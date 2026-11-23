"""RunOutput.from_dict hands back the status enum that readers such as print_response expect."""

from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput


def test_from_dict_returns_the_status_enum():
    restored = RunOutput.from_dict({"run_id": "r1", "status": "COMPLETED", "content": "x"})
    assert restored.status is RunStatus.completed
    assert restored.status.value == "COMPLETED"


def test_from_dict_keeps_an_unknown_status_string():
    restored = RunOutput.from_dict({"run_id": "r1", "status": "SOMETHING_NEW"})
    assert restored.status == "SOMETHING_NEW"


def test_round_trip_keeps_the_enum():
    original = RunOutput(run_id="r1", status=RunStatus.cancelled)
    assert RunOutput.from_dict(original.to_dict()).status is RunStatus.cancelled


def test_team_from_dict_returns_the_status_enum():
    restored = TeamRunOutput.from_dict({"run_id": "r1", "status": "COMPLETED"})
    assert restored.status is RunStatus.completed
    assert restored.status.value == "COMPLETED"


def test_team_from_dict_keeps_an_unknown_status_string():
    restored = TeamRunOutput.from_dict({"run_id": "r1", "status": "SOMETHING_NEW"})
    assert restored.status == "SOMETHING_NEW"


def test_team_round_trip_keeps_the_enum():
    original = TeamRunOutput(run_id="r1", status=RunStatus.cancelled)
    assert TeamRunOutput.from_dict(original.to_dict()).status is RunStatus.cancelled


def test_team_stored_status_supports_value_readers():
    # AgentOS readers emit restored.status.value; a plain str would raise AttributeError.
    restored = TeamRunOutput.from_dict(TeamRunOutput(run_id="r1").to_dict())
    assert restored.status.value == "RUNNING"


def test_workflow_from_dict_returns_the_status_enum():
    restored = WorkflowRunOutput.from_dict({"run_id": "r1", "status": "COMPLETED"})
    assert restored.status is RunStatus.completed
    assert restored.status.value == "COMPLETED"


def test_workflow_from_dict_keeps_an_unknown_status_string():
    restored = WorkflowRunOutput.from_dict({"run_id": "r1", "status": "SOMETHING_NEW"})
    assert restored.status == "SOMETHING_NEW"


def test_workflow_round_trip_keeps_the_enum():
    original = WorkflowRunOutput(run_id="r1", status=RunStatus.cancelled)
    assert WorkflowRunOutput.from_dict(original.to_dict()).status is RunStatus.cancelled


def test_workflow_stored_status_supports_value_readers():
    # AgentOS readers emit restored.status.value; a plain str would raise AttributeError.
    restored = WorkflowRunOutput.from_dict(WorkflowRunOutput(run_id="r1").to_dict())
    assert restored.status.value == "PENDING"
