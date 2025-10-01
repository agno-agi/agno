import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from agno.run.base import BaseRunOutputEvent


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
