import pytest

from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput


@pytest.mark.parametrize(
    ("output_cls", "kwargs"),
    [
        (RunOutput, {"run_id": "agent-run-1"}),
        (TeamRunOutput, {"run_id": "team-run-1", "team_id": "team-1"}),
        (WorkflowRunOutput, {"run_id": "workflow-run-1", "workflow_id": "workflow-1"}),
    ],
)
def test_run_output_from_dict_restores_run_status_enum(output_cls, kwargs):
    run_output = output_cls(status=RunStatus.completed, **kwargs)

    restored = output_cls.from_dict(run_output.to_dict())

    assert restored.status is RunStatus.completed
    assert restored.status.value == "COMPLETED"


@pytest.mark.parametrize(
    ("output_cls", "kwargs"),
    [
        (RunOutput, {"run_id": "agent-run-1"}),
        (TeamRunOutput, {"run_id": "team-run-1", "team_id": "team-1"}),
        (WorkflowRunOutput, {"run_id": "workflow-run-1", "workflow_id": "workflow-1"}),
    ],
)
def test_run_output_from_dict_preserves_unknown_status_string(output_cls, kwargs):
    restored = output_cls.from_dict({"status": "LEGACY_STATUS", **kwargs})

    assert restored.status == "LEGACY_STATUS"
