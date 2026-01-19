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


def test_agent_session_state_in_run_output():
    """Test that RunOutput includes session_state field."""
    from agno.run.agent import RunOutput

    run_output = RunOutput(run_id="test_123", session_state={"key": "value", "counter": 10})

    assert run_output.session_state == {"key": "value", "counter": 10}

    # Test serialization
    run_dict = run_output.to_dict()
    assert "session_state" in run_dict
    assert run_dict["session_state"] == {"key": "value", "counter": 10}

    # Test deserialization
    reconstructed = RunOutput.from_dict(run_dict)
    assert reconstructed.session_state == {"key": "value", "counter": 10}


def test_agent_session_state_in_completed_event():
    """Test that RunCompletedEvent includes session_state field."""
    from agno.run.agent import RunOutput
    from agno.utils.events import create_run_completed_event

    run_output = RunOutput(
        run_id="test_123",
        agent_id="agent_456",
        agent_name="TestAgent",
        session_state={"user_name": "Alice", "count": 5},
    )

    event = create_run_completed_event(from_run_response=run_output)

    assert event.session_state == {"user_name": "Alice", "count": 5}
    assert event.run_id == "test_123"

    # Test event serialization
    event_dict = event.to_dict()
    assert "session_state" in event_dict
    assert event_dict["session_state"] == {"user_name": "Alice", "count": 5}


def test_team_session_state_in_run_output():
    """Test that TeamRunOutput includes session_state field."""
    from agno.run.team import TeamRunOutput

    team_output = TeamRunOutput(run_id="team_123", team_id="team_456", session_state={"phase": "planning", "tasks": 3})

    assert team_output.session_state == {"phase": "planning", "tasks": 3}

    # Test serialization
    team_dict = team_output.to_dict()
    assert "session_state" in team_dict
    assert team_dict["session_state"] == {"phase": "planning", "tasks": 3}

    # Test deserialization
    reconstructed = TeamRunOutput.from_dict(team_dict)
    assert reconstructed.session_state == {"phase": "planning", "tasks": 3}


def test_team_session_state_in_completed_event():
    """Test that TeamRunCompletedEvent includes session_state field."""
    from agno.run.team import TeamRunOutput
    from agno.utils.events import create_team_run_completed_event

    team_output = TeamRunOutput(
        run_id="team_123", team_id="team_456", team_name="TestTeam", session_state={"status": "active", "progress": 75}
    )

    event = create_team_run_completed_event(from_run_response=team_output)

    assert event.session_state == {"status": "active", "progress": 75}
    assert event.run_id == "team_123"

    # Test event serialization
    event_dict = event.to_dict()
    assert "session_state" in event_dict
    assert event_dict["session_state"] == {"status": "active", "progress": 75}


def test_session_state_mutability():
    """Test that session_state dict is passed by reference."""
    from agno.run.agent import RunOutput
    from agno.utils.events import create_run_completed_event

    session_state = {"value": 1}
    run_output = RunOutput(run_id="test_123", session_state=session_state)

    # Modify original dict
    session_state["value"] = 2
    session_state["new_key"] = "added"

    # Changes should be reflected in RunOutput
    assert run_output.session_state == {"value": 2, "new_key": "added"}

    # Event should get updated state
    event = create_run_completed_event(from_run_response=run_output)
    assert event.session_state == {"value": 2, "new_key": "added"}


def test_api_schema_session_state():
    """Test that API schemas include session_state."""
    from agno.os.schema import RunSchema, TeamRunSchema
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

    # Test RunSchema
    run_output = RunOutput(run_id="test_123", session_state={"api_data": "value"})
    run_dict = run_output.to_dict()
    api_schema = RunSchema.from_dict(run_dict)
    assert api_schema.session_state == {"api_data": "value"}

    # Verify API response includes it
    api_response = api_schema.model_dump(exclude_none=True)
    assert "session_state" in api_response
    assert api_response["session_state"] == {"api_data": "value"}

    # Test TeamRunSchema
    team_output = TeamRunOutput(run_id="team_123", team_id="team_456", session_state={"team_api_data": "value"})
    team_dict = team_output.to_dict()
    team_schema = TeamRunSchema.from_dict(team_dict)
    assert team_schema.session_state == {"team_api_data": "value"}

    # Verify API response includes it
    team_api_response = team_schema.model_dump(exclude_none=True)
    assert "session_state" in team_api_response
    assert team_api_response["session_state"] == {"team_api_data": "value"}


def test_requirements_in_run_paused_event():
    """Test that RunPausedEvent includes requirements field and serializes/deserializes properly."""
    from agno.models.response import ToolExecution
    from agno.run.agent import RunPausedEvent
    from agno.run.requirement import RunRequirement

    # Create a ToolExecution that requires confirmation
    tool_execution = ToolExecution(
        tool_call_id="call_123",
        tool_name="get_the_weather",
        tool_args={"city": "Tokyo"},
        requires_confirmation=True,
    )

    # Create a RunRequirement from the tool execution
    requirement = RunRequirement(tool_execution=tool_execution)

    # Create a RunPausedEvent with the requirement
    paused_event = RunPausedEvent(
        run_id="run_456",
        agent_id="agent_789",
        agent_name="TestAgent",
        tools=[tool_execution],
        requirements=[requirement],
    )

    # Test that requirements field exists and is properly set
    assert paused_event.requirements is not None
    assert len(paused_event.requirements) == 1
    assert paused_event.requirements[0].tool_execution.tool_name == "get_the_weather"
    assert paused_event.requirements[0].tool_execution.requires_confirmation is True

    # Test to_dict serialization
    event_dict = paused_event.to_dict()
    assert "requirements" in event_dict
    assert len(event_dict["requirements"]) == 1
    assert event_dict["requirements"][0]["tool_execution"]["tool_name"] == "get_the_weather"
    assert event_dict["requirements"][0]["tool_execution"]["requires_confirmation"] is True

    # Test from_dict deserialization
    reconstructed = RunPausedEvent.from_dict(event_dict)
    assert reconstructed.requirements is not None
    assert len(reconstructed.requirements) == 1
    assert reconstructed.requirements[0].tool_execution.tool_name == "get_the_weather"
    assert reconstructed.requirements[0].tool_execution.requires_confirmation is True
    assert reconstructed.requirements[0].needs_confirmation is True
