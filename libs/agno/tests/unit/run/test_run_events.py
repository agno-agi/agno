import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from agno.run.base import BaseRunOutputEvent
from agno.run.workflow import BaseWorkflowRunOutputEvent


class RunEnum(Enum):
    NY = "New York"
    LA = "Los Angeles"
    SF = "San Francisco"
    CHI = "Chicago"


@dataclass
class SampleRunEvent(BaseRunOutputEvent):
    date: datetime
    location: RunEnum
    name: str
    age: int


@dataclass
class SampleWorkflowRunEvent(BaseWorkflowRunOutputEvent):
    date: datetime = field(default_factory=lambda: datetime.now())
    location: RunEnum = RunEnum.NY
    name: str = ""
    age: int = 0


def test_run_events():
    now = datetime(2025, 1, 1, 12, 0, 0)

    event = SampleRunEvent(
        date=now,
        location=RunEnum.NY,
        name="John Doe",
        age=30,
    )

    # to_dict returns native Python types
    d = event.to_dict()
    assert d["date"] == now
    assert d["location"] == RunEnum.NY
    assert d["name"] == "John Doe"
    assert d["age"] == 30

    # to_json should contain serialized values; compare as dict
    expected_json_dict = {
        "date": now.isoformat(),
        "location": RunEnum.NY.value,
        "name": "John Doe",
        "age": 30,
    }
    assert json.loads(event.to_json(indent=None)) == expected_json_dict


def test_workflow_run_events():
    now = datetime(2025, 1, 1, 12, 0, 0)

    event = SampleWorkflowRunEvent(
        date=now,
        location=RunEnum.NY,
        name="John Doe",
        age=30,
    )

    # to_dict returns native Python types
    d = event.to_dict()
    assert d["date"] == now
    assert d["location"] == RunEnum.NY
    assert d["name"] == "John Doe"
    assert d["age"] == 30

    # to_json should contain serialized values; compare as dict
    expected_json_dict = {
        "date": now.isoformat(),
        "location": RunEnum.NY.value,
        "name": "John Doe",
        "age": 30,
        "created_at": event.created_at,
        "event": "",
    }
    assert json.loads(event.to_json(indent=None)) == expected_json_dict
