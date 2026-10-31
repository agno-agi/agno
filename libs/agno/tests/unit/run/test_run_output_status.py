"""RunOutput.from_dict hands back the status enum that readers such as print_response expect."""

from agno.run.agent import RunOutput
from agno.run.base import RunStatus


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
