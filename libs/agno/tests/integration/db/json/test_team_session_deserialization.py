"""
Integration tests for JsonDb Team session deserialization.
Specifically tests the fix for issue #4894 where Team sessions
with mixed RunOutput and TeamRunOutput types failed to deserialize.
"""

import tempfile
import os

import pytest

from agno.db.base import SessionType
from agno.db.json import JsonDb
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession


@pytest.fixture
def temp_json_db():
    """Create a temporary JsonDb for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db = JsonDb(db_path=temp_dir, session_table="test_sessions")
        yield db


def test_jsondb_deserialize_team_session_with_mixed_runs(temp_json_db):
    """
    Test that JsonDb can correctly deserialize Team sessions containing
    both RunOutput (agent runs with agent_id) and TeamRunOutput (team runs with team_id).

    This is a regression test for issue #4894.
    """
    session_id = "test_mixed_runs_session"
    team_id = "test_team"
    user_id = "test_user"

    # Create a RunOutput (simulating an agent run)
    agent_run = RunOutput(
        run_id="agent_run_1",
        agent_id="member_agent_1",
        agent_name="Member Agent",
        session_id=session_id,
        user_id=user_id,
        content="Agent response content",
        messages=[],
    )

    # Create a TeamRunOutput (simulating a team run)
    team_run = TeamRunOutput(
        run_id="team_run_1",
        team_id=team_id,
        team_name="Test Team",
        session_id=session_id,
        content="Team response content",
        messages=[],
        member_responses=[],  # member_responses would typically contain agent_run
    )

    # Create a Team session with both run types
    team_session = TeamSession(
        session_id=session_id,
        team_id=team_id,
        user_id=user_id,
        runs=[agent_run, team_run],  # Mixed run types
    )

    # Store the session
    temp_json_db.upsert_session(team_session)

    # Read the session back - this is where the bug occurred
    # Before fix: Would raise TypeError: TeamRunOutput.__init__() got an unexpected keyword argument 'agent_id'
    retrieved_session = temp_json_db.get_session(
        session_id=session_id, session_type=SessionType.TEAM, deserialize=True
    )

    # Verify the session was correctly deserialized
    assert retrieved_session is not None
    assert isinstance(retrieved_session, TeamSession)
    assert retrieved_session.session_id == session_id
    assert retrieved_session.team_id == team_id

    # Verify both runs are present and correctly typed
    assert retrieved_session.runs is not None
    assert len(retrieved_session.runs) == 2

    # Check the types are correct
    run_types = [type(run).__name__ for run in retrieved_session.runs]
    assert "RunOutput" in run_types, "Should have deserialized RunOutput (agent run)"
    assert "TeamRunOutput" in run_types, "Should have deserialized TeamRunOutput (team run)"

    # Verify the agent run
    agent_runs = [run for run in retrieved_session.runs if isinstance(run, RunOutput)]
    assert len(agent_runs) == 1
    assert agent_runs[0].agent_id == "member_agent_1"
    assert agent_runs[0].run_id == "agent_run_1"

    # Verify the team run
    team_runs = [run for run in retrieved_session.runs if isinstance(run, TeamRunOutput)]
    assert len(team_runs) == 1
    assert team_runs[0].team_id == team_id
    assert team_runs[0].run_id == "team_run_1"


def test_jsondb_deserialize_team_run_with_user_id_field(temp_json_db):
    """
    Test that TeamRunOutput.from_dict correctly handles extra fields like user_id
    that are not part of TeamRunOutput's schema but might be present in stored data.

    This is part of the fix for issue #4894.
    """
    session_id = "test_extra_fields_session"
    team_id = "test_team"
    user_id = "test_user"

    # Create a TeamRunOutput that includes extra fields when serialized
    team_run = TeamRunOutput(
        run_id="team_run_with_extras",
        team_id=team_id,
        team_name="Test Team",
        session_id=session_id,
        content="Team response",
        messages=[],
        member_responses=[],
    )

    team_session = TeamSession(
        session_id=session_id,
        team_id=team_id,
        user_id=user_id,  # This user_id might leak into run data
        runs=[team_run],
    )

    # Store and retrieve
    temp_json_db.upsert_session(team_session)

    # Manually add user_id to the run data in the JSON to simulate the bug scenario
    import json

    json_file = os.path.join(temp_json_db.db_path, "test_sessions.json")
    with open(json_file, "r") as f:
        data = json.load(f)

    # Add user_id to the team run to simulate data that triggers the bug
    if data and data[0]["runs"]:
        data[0]["runs"][0]["user_id"] = user_id
        data[0]["runs"][0]["workflow_id"] = "some_workflow"

    with open(json_file, "w") as f:
        json.dump(data, f)

    # Now try to read it back - this should not fail
    # Before fix: Would raise TypeError: TeamRunOutput.__init__() got an unexpected keyword argument 'user_id'
    retrieved_session = temp_json_db.get_session(
        session_id=session_id, session_type=SessionType.TEAM, deserialize=True
    )

    assert retrieved_session is not None
    assert len(retrieved_session.runs) == 1
    assert isinstance(retrieved_session.runs[0], TeamRunOutput)


def test_jsondb_handles_empty_runs_list(temp_json_db):
    """Test that JsonDb correctly handles Team sessions with empty runs list."""
    session_id = "test_empty_runs"
    team_id = "test_team"

    team_session = TeamSession(
        session_id=session_id,
        team_id=team_id,
        runs=[],  # Empty runs list
    )

    temp_json_db.upsert_session(team_session)

    retrieved_session = temp_json_db.get_session(
        session_id=session_id, session_type=SessionType.TEAM, deserialize=True
    )

    assert retrieved_session is not None
    assert retrieved_session.runs is not None
    assert len(retrieved_session.runs) == 0


def test_jsondb_agent_only_runs_in_team_session(temp_json_db):
    """Test Team session containing only agent runs (no team runs)."""
    session_id = "test_agent_only"
    team_id = "test_team"

    # Only agent runs, no team runs
    agent_run1 = RunOutput(
        run_id="agent_run_1",
        agent_id="agent_1",
        session_id=session_id,
        content="Agent 1 response",
        messages=[],
    )

    agent_run2 = RunOutput(
        run_id="agent_run_2",
        agent_id="agent_2",
        session_id=session_id,
        content="Agent 2 response",
        messages=[],
    )

    team_session = TeamSession(
        session_id=session_id,
        team_id=team_id,
        runs=[agent_run1, agent_run2],
    )

    temp_json_db.upsert_session(team_session)

    retrieved_session = temp_json_db.get_session(
        session_id=session_id, session_type=SessionType.TEAM, deserialize=True
    )

    assert retrieved_session is not None
    assert len(retrieved_session.runs) == 2
    assert all(isinstance(run, RunOutput) for run in retrieved_session.runs)
    assert all(run.agent_id is not None for run in retrieved_session.runs)


def test_jsondb_team_only_runs_in_team_session(temp_json_db):
    """Test Team session containing only team runs (no agent runs)."""
    session_id = "test_team_only"
    team_id = "test_team"

    # Only team runs, no agent runs
    team_run1 = TeamRunOutput(
        run_id="team_run_1",
        team_id=team_id,
        session_id=session_id,
        content="Team response 1",
        messages=[],
        member_responses=[],
    )

    team_run2 = TeamRunOutput(
        run_id="team_run_2",
        team_id=team_id,
        session_id=session_id,
        content="Team response 2",
        messages=[],
        member_responses=[],
    )

    team_session = TeamSession(
        session_id=session_id,
        team_id=team_id,
        runs=[team_run1, team_run2],
    )

    temp_json_db.upsert_session(team_session)

    retrieved_session = temp_json_db.get_session(
        session_id=session_id, session_type=SessionType.TEAM, deserialize=True
    )

    assert retrieved_session is not None
    assert len(retrieved_session.runs) == 2
    assert all(isinstance(run, TeamRunOutput) for run in retrieved_session.runs)
    assert all(run.team_id is not None for run in retrieved_session.runs)

