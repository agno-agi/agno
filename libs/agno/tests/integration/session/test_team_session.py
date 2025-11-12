"""Integration tests for TeamSession methods"""

import uuid
from datetime import datetime
from time import time

from agno.db.base import SessionType
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.summary import SessionSummary
from agno.session.team import TeamSession


def create_session_with_runs(shared_db, session_id: str, runs: list[TeamRunOutput | RunOutput]) -> TeamSession:
    """Helper function to create and store a session with runs in the database"""
    team_session = TeamSession(session_id=session_id, team_id="test_team", runs=runs, created_at=int(time()))

    # Store the session in the database
    shared_db.upsert_session(session=team_session)

    # Retrieve it back to ensure it's properly persisted
    return shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)


def test_get_messages_basic(shared_db):
    """Test basic functionality of getting messages from last N runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create 3 runs with messages
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="First user message"),
                Message(role="assistant", content="First assistant response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Second user message"),
                Message(role="assistant", content="Second assistant response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run3",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Third user message"),
                Message(role="assistant", content="Third assistant response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id=session_id, runs=runs)
    assert team_session is not None
    assert len(team_session.runs) == 3

    # Test getting messages from last 2 runs
    messages = team_session.get_messages(last_n_runs=2)

    # Should get 4 messages (2 from each of the last 2 runs)
    assert len(messages) == 4
    assert messages[0].content == "Second user message"
    assert messages[1].content == "Second assistant response"
    assert messages[2].content == "Third user message"
    assert messages[3].content == "Third assistant response"

    # Verify messages are not from history
    for msg in messages:
        assert not msg.from_history


def test_get_messages_with_limit(shared_db):
    """Test getting last N messages instead of last N runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs with system messages
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="First message"),
                Message(role="assistant", content="First response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Second message"),
                Message(role="assistant", content="Second response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run3",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Third message"),
                Message(role="assistant", content="Third response"),
                Message(role="user", content="Fourth message"),
                Message(role="assistant", content="Fourth response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)
    assert team_session is not None

    # Test getting last 3 messages (should get system message + last 2 non-system messages)
    messages = team_session.get_messages(limit=3)

    assert len(messages) == 3
    # System message should be first
    assert messages[0].role == "system"
    assert messages[0].content == "System prompt"
    # Then the last 2 non-system messages
    assert messages[1].content == "Fourth message"
    assert messages[2].content == "Fourth response"


def test_get_messages_with_limit_skip_system_message(shared_db):
    """Test getting last N messages with skipping system messages"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs with system messages
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="First message"),
                Message(role="assistant", content="First response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Second message"),
                Message(role="assistant", content="Second response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run3",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Third message"),
                Message(role="assistant", content="Third response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)
    assert team_session is not None

    # Test getting last 3 messages (should get last 3 non-system messages)
    messages = team_session.get_messages(limit=3, skip_roles=["system"])

    assert len(messages) == 3
    # Then the last 3 non-system messages
    assert messages[0].content == "Second response"
    assert messages[1].content == "Third message"
    assert messages[2].content == "Third response"


def test_get_messages_with_last_n_messages_skip_incomplete_tool_results(shared_db):
    """Test getting last N messages and skipping incomplete tool results"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs with system messages
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Third message"),
                Message(
                    role="assistant",
                    content="Third response",
                    tool_calls=[{"id": "tool_call_id_1"}, {"id": "tool_call_id_2"}],
                ),
                Message(role="tool", content="Tool result 1", tool_call_id="tool_call_id_1"),
                Message(role="tool", content="Tool result 2", tool_call_id="tool_call_id_2"),
                Message(role="assistant", content="Assistant response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)
    assert team_session is not None

    # This will include the tool result only, but we don't want to include it without an associated assistant response with tool calls
    messages = team_session.get_messages(limit=3, skip_roles=["system"])

    assert len(messages) == 1
    # Then the assistant response with the tool call
    assert messages[0].content == "Assistant response"

    # This will include the tool result and the assistant response with the tool call
    messages = team_session.get_messages(limit=4, skip_roles=["system"])

    assert len(messages) == 4
    # Then the assistant response with the tool call
    assert messages[0].content == "Third response"
    assert messages[1].content == "Tool result 1"
    assert messages[2].content == "Tool result 2"
    assert messages[3].content == "Assistant response"


def test_get_messages_skip_history_messages(shared_db):
    """Test that messages tagged as from_history are skipped"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs with some messages marked as history
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Old message", from_history=True),
                Message(role="assistant", content="Old response", from_history=True),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="New message", from_history=False),
                Message(role="assistant", content="New response", from_history=False),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages with skip_history_messages=True (default)
    messages = team_session.get_messages(skip_history_messages=True)

    # Should only get messages from run2 that are not from history
    assert len(messages) == 2
    assert all(not msg.from_history for msg in messages)
    assert messages[0].content == "New message"
    assert messages[1].content == "New response"

    # Get messages with skip_history_messages=False
    messages_with_history = team_session.get_messages(skip_history_messages=False)

    # Should get all messages including history
    assert len(messages_with_history) == 4


def test_get_messages_skip_role(shared_db):
    """Test skipping messages with specific role"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="User message"),
                Message(role="assistant", content="Assistant response"),
                Message(role="tool", content="Tool result"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Skip system messages
    messages = team_session.get_messages(skip_roles=["system"])

    assert len(messages) == 3
    assert all(msg.role != "system" for msg in messages)

    # Skip tool messages
    messages_no_tool = team_session.get_messages(skip_roles=["tool"])

    assert len(messages_no_tool) == 3
    assert all(msg.role != "tool" for msg in messages_no_tool)


def test_get_messages_skip_status(shared_db):
    """Test skipping runs with specific status"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs with different statuses
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run_completed",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Completed run"),
                Message(role="assistant", content="Completed response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run_error",
            status=RunStatus.error,
            messages=[
                Message(role="user", content="Error run"),
                Message(role="assistant", content="Error response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run_cancelled",
            status=RunStatus.cancelled,
            messages=[
                Message(role="user", content="Cancelled run"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # By default, should skip error, cancelled, and paused runs
    messages = team_session.get_messages()

    assert len(messages) == 2  # Only messages from completed run
    assert messages[0].content == "Completed run"
    assert messages[1].content == "Completed response"

    # Explicitly skip only error status
    messages_skip_error = team_session.get_messages(skip_statuses=[RunStatus.error])

    # Should get messages from completed and cancelled runs
    assert len(messages_skip_error) == 3


def test_get_messages_filter_by_agent_id(shared_db):
    """Test filtering messages by agent_id for member runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs from different agents
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="agent_1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Agent 1 message"),
                Message(role="assistant", content="Agent 1 response"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="agent_2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Agent 2 message"),
                Message(role="assistant", content="Agent 2 response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages only from agent_1
    messages_agent1 = team_session.get_messages(member_ids=["agent_1"])

    assert len(messages_agent1) == 2
    assert messages_agent1[0].content == "Agent 1 message"
    assert messages_agent1[1].content == "Agent 1 response"

    # Get messages only from agent_2
    messages_agent2 = team_session.get_messages(member_ids=["agent_2"])

    assert len(messages_agent2) == 2
    assert messages_agent2[0].content == "Agent 2 message"
    assert messages_agent2[1].content == "Agent 2 response"


def test_get_messages_filter_by_team_id(shared_db):
    """Test filtering messages by team_id"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs from different teams
    runs = [
        TeamRunOutput(
            run_id="run1",
            team_id="team_1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Team 1 message"),
                Message(role="assistant", content="Team 1 response"),
            ],
        ),
        TeamRunOutput(
            run_id="run2",
            team_id="team_2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Team 2 message"),
                Message(role="assistant", content="Team 2 response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages only from team_1
    messages_team1 = team_session.get_messages(team_id="team_1")

    assert len(messages_team1) == 2
    assert messages_team1[0].content == "Team 1 message"
    assert messages_team1[1].content == "Team 1 response"

    # Get messages only from team_2
    messages_team2 = team_session.get_messages(team_id="team_2")

    assert len(messages_team2) == 2
    assert messages_team2[0].content == "Team 2 message"
    assert messages_team2[1].content == "Team 2 response"


def test_get_messages_filter_member_runs(shared_db):
    """Test filtering member runs vs team leader runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs with parent_run_id (member runs) and without (team leader runs)
    runs = [
        TeamRunOutput(
            run_id="team_run1",
            team_id="test_team",
            status=RunStatus.completed,
            parent_run_id=None,
            messages=[
                Message(role="user", content="Team leader message"),
                Message(role="assistant", content="Team leader response"),
            ],
        ),
        RunOutput(
            run_id="member_run1",
            agent_id="agent_1",
            parent_run_id="team_run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Member message"),
                Message(role="assistant", content="Member response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # By default, should only get team leader runs
    messages_leader = team_session.get_messages()

    assert len(messages_leader) == 2
    assert messages_leader[0].content == "Team leader message"
    assert messages_leader[1].content == "Team leader response"

    # Get member runs
    messages_members = team_session.get_messages(skip_member_messages=False)

    # Should get all messages including member runs
    assert len(messages_members) == 4


def test_get_messages_system_message_handling(shared_db):
    """Test that system messages are handled correctly and only added once"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs each with system messages
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="First message"),
                Message(role="assistant", content="First response"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Second message"),
                Message(role="assistant", content="Second response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get all messages
    messages = team_session.get_messages()

    # Count system messages - should only be 1
    system_messages = [msg for msg in messages if msg.role == "system"]
    assert len(system_messages) == 1

    # System message should be first
    assert messages[0].role == "system"


def test_get_messages_empty_session(shared_db):
    """Test getting messages from an empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create session with no runs
    team_session = create_session_with_runs(shared_db, session_id, [])

    # Get messages from empty session
    messages = team_session.get_messages()

    assert len(messages) == 0


def test_get_messages_last_n_with_multiple_runs(shared_db):
    """Test getting messages from specific number of last runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create 5 runs
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id=f"run{i}",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content=f"Message {i}"),
                Message(role="assistant", content=f"Response {i}"),
            ],
        )
        for i in range(5)
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages from last 2 runs only
    messages = team_session.get_messages(last_n_runs=2)

    # Should have 4 messages (2 messages per run * 2 runs)
    assert len(messages) == 4

    # Verify we got the last 2 runs (runs 3 and 4)
    assert messages[0].content == "Message 3"
    assert messages[1].content == "Response 3"
    assert messages[2].content == "Message 4"
    assert messages[3].content == "Response 4"

    # Get messages from last 1 run
    messages_one_run = team_session.get_messages(last_n_runs=1)

    # Should have 2 messages from the last run
    assert len(messages_one_run) == 2
    assert messages_one_run[0].content == "Message 4"
    assert messages_one_run[1].content == "Response 4"


def test_get_messages_with_none_messages_in_run(shared_db):
    """Test handling runs with no messages"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create run with None messages and run with valid messages
    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=None,
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Valid message"),
                Message(role="assistant", content="Valid response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Should handle None messages gracefully
    messages = team_session.get_messages()

    assert len(messages) == 2
    assert messages[0].content == "Valid message"


def test_get_messages_combined_filters(shared_db):
    """Test combining multiple filters"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs with various characteristics
    runs = [
        TeamRunOutput(
            run_id="run1",
            team_id="team_1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System"),
                Message(role="user", content="Team 1 user", from_history=True),
                Message(role="assistant", content="Team 1 assistant"),
            ],
        ),
        TeamRunOutput(
            run_id="run2",
            team_id="team_1",
            status=RunStatus.error,
            messages=[
                Message(role="user", content="Error run"),
            ],
        ),
        TeamRunOutput(
            run_id="run3",
            team_id="team_1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Team 1 new user"),
                Message(role="assistant", content="Team 1 new assistant"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Filter by team_id, skip error status, skip history messages, and skip system role
    messages = team_session.get_messages(
        team_id="team_1",
        skip_statuses=[RunStatus.error],
        skip_history_messages=True,
        skip_roles=["system"],
    )

    # Should get messages from run1 and run3, excluding system, history, and error runs
    # From run1: only assistant message (user is history, system is skipped)
    # From run3: both user and assistant
    assert len(messages) == 3
    assert messages[0].content == "Team 1 assistant"
    assert messages[1].content == "Team 1 new user"
    assert messages[2].content == "Team 1 new assistant"


# Tests for to_dict() and from_dict()
def test_to_dict_basic(shared_db):
    """Test converting TeamSession to dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Test message"),
                Message(role="assistant", content="Test response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Convert to dict
    session_dict = team_session.to_dict()

    assert session_dict["session_id"] == session_id
    assert session_dict["team_id"] == "test_team"
    assert session_dict["runs"] is not None
    assert len(session_dict["runs"]) == 1
    assert session_dict["runs"][0]["run_id"] == "run1"


def test_to_dict_with_summary(shared_db):
    """Test converting TeamSession with summary to dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    summary = SessionSummary(
        summary="Test session summary",
        topics=["topic1", "topic2"],
        updated_at=datetime.now(),
    )

    team_session = TeamSession(
        session_id=session_id,
        team_id="test_team",
        summary=summary,
        created_at=int(time()),
    )

    shared_db.upsert_session(session=team_session)
    retrieved_session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)

    # Convert to dict
    session_dict = retrieved_session.to_dict()

    assert session_dict["summary"] is not None
    assert session_dict["summary"]["summary"] == "Test session summary"
    assert session_dict["summary"]["topics"] == ["topic1", "topic2"]


def test_from_dict_basic(shared_db):
    """Test creating TeamSession from dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    session_data = {
        "session_id": session_id,
        "team_id": "test_team",
        "user_id": "test_user",
        "session_data": {"key": "value"},
        "metadata": {"meta_key": "meta_value"},
        "runs": [
            {
                "run_id": "run1",
                "team_id": "test_team",
                "status": RunStatus.completed,
                "messages": [
                    {"role": "user", "content": "Test message"},
                    {"role": "assistant", "content": "Test response"},
                ],
            }
        ],
    }

    # Create from dict
    team_session = TeamSession.from_dict(session_data)

    assert team_session is not None
    assert team_session.session_id == session_id
    assert team_session.team_id == "test_team"
    assert team_session.user_id == "test_user"
    assert team_session.session_data == {"key": "value"}
    assert team_session.metadata == {"meta_key": "meta_value"}
    assert len(team_session.runs) == 1
    assert team_session.runs[0].run_id == "run1"


def test_from_dict_missing_session_id(shared_db):
    """Test that from_dict returns None when session_id is missing"""
    session_data = {
        "team_id": "test_team",
        "runs": [],
    }

    # Should return None with missing session_id
    team_session = TeamSession.from_dict(session_data)

    assert team_session is None


def test_from_dict_with_summary(shared_db):
    """Test creating TeamSession with summary from dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    session_data = {
        "session_id": session_id,
        "summary": {
            "summary": "Test summary",
            "topics": ["topic1"],
            "updated_at": datetime.now().isoformat(),
        },
    }

    team_session = TeamSession.from_dict(session_data)

    assert team_session is not None
    assert team_session.summary is not None
    assert team_session.summary.summary == "Test summary"
    assert team_session.summary.topics == ["topic1"]


def test_from_dict_mixed_run_types(shared_db):
    """Test creating TeamSession with both TeamRunOutput and RunOutput"""
    session_id = f"test_session_{uuid.uuid4()}"

    session_data = {
        "session_id": session_id,
        "team_id": "test_team",
        "runs": [
            {
                "run_id": "team_run",
                "team_id": "test_team",
                "status": RunStatus.completed,
                "messages": [{"role": "user", "content": "Team message"}],
            },
            {
                "run_id": "agent_run",
                "agent_id": "agent_1",
                "status": RunStatus.completed,
                "messages": [{"role": "user", "content": "Agent message"}],
            },
        ],
    }

    team_session = TeamSession.from_dict(session_data)

    assert team_session is not None
    assert len(team_session.runs) == 2
    # First should be TeamRunOutput
    assert isinstance(team_session.runs[0], TeamRunOutput)
    # Second should be RunOutput
    assert isinstance(team_session.runs[1], RunOutput)


# Tests for upsert_run()
def test_upsert_run_add_new(shared_db):
    """Test adding a new run to session"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Add a new run
    new_run = TeamRunOutput(
        team_id="test_team",
        run_id="run1",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="New message"),
            Message(role="assistant", content="New response"),
        ],
    )

    team_session.upsert_run(new_run)

    assert len(team_session.runs) == 1
    assert team_session.runs[0].run_id == "run1"


def test_upsert_run_update_existing(shared_db):
    """Test updating an existing run"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Original message"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Update existing run
    updated_run = TeamRunOutput(
        team_id="test_team",
        run_id="run1",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Updated message"),
            Message(role="assistant", content="Updated response"),
        ],
    )

    team_session.upsert_run(updated_run)

    # Should still have only 1 run, but with updated content
    assert len(team_session.runs) == 1
    assert team_session.runs[0].run_id == "run1"
    assert len(team_session.runs[0].messages) == 2
    assert team_session.runs[0].messages[0].content == "Updated message"


def test_upsert_run_multiple(shared_db):
    """Test adding multiple runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Add multiple runs
    for i in range(3):
        run = TeamRunOutput(
            team_id="test_team",
            run_id=f"run{i}",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content=f"Message {i}"),
            ],
        )
        team_session.upsert_run(run)

    assert len(team_session.runs) == 3
    assert team_session.runs[0].run_id == "run0"
    assert team_session.runs[1].run_id == "run1"
    assert team_session.runs[2].run_id == "run2"


# Tests for get_run()
def test_get_run_exists(shared_db):
    """Test retrieving an existing run"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[Message(role="user", content="Message 1")],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[Message(role="user", content="Message 2")],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get specific run
    run = team_session.get_run("run2")

    assert run is not None
    assert run.run_id == "run2"
    assert run.messages[0].content == "Message 2"


def test_get_run_not_exists(shared_db):
    """Test retrieving a non-existent run"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[Message(role="user", content="Message 1")],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Try to get non-existent run
    run = team_session.get_run("non_existent")

    assert run is None


def test_get_run_empty_session(shared_db):
    """Test retrieving run from empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Try to get run from empty session
    run = team_session.get_run("run1")

    assert run is None


# Tests for get_tool_calls()
def test_get_tool_calls_basic(shared_db):
    """Test retrieving tool calls from messages"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Use a tool"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        {
                            "id": "call1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"query": "test"}'},
                        }
                    ],
                ),
                Message(role="tool", content="Tool result"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get tool calls
    tool_calls = team_session.get_tool_calls()

    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call1"
    assert tool_calls[0]["function"]["name"] == "search"


def test_get_tool_calls_multiple_runs(shared_db):
    """Test retrieving tool calls from multiple runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(
                    role="assistant",
                    tool_calls=[{"id": "call1", "type": "function"}],
                ),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(
                    role="assistant",
                    tool_calls=[
                        {"id": "call2", "type": "function"},
                        {"id": "call3", "type": "function"},
                    ],
                ),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get all tool calls (should be in reverse order - most recent first)
    tool_calls = team_session.get_tool_calls()

    assert len(tool_calls) == 3
    # Should be reversed (run2 before run1)
    assert tool_calls[0]["id"] == "call2"
    assert tool_calls[1]["id"] == "call3"
    assert tool_calls[2]["id"] == "call1"


def test_get_tool_calls_with_limit(shared_db):
    """Test retrieving limited number of tool calls"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(
                    role="assistant",
                    tool_calls=[
                        {"id": "call1", "type": "function"},
                        {"id": "call2", "type": "function"},
                        {"id": "call3", "type": "function"},
                    ],
                ),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get only 2 tool calls
    tool_calls = team_session.get_tool_calls(num_calls=2)

    assert len(tool_calls) == 2
    assert tool_calls[0]["id"] == "call1"
    assert tool_calls[1]["id"] == "call2"


def test_get_tool_calls_no_tools(shared_db):
    """Test retrieving tool calls when there are none"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="No tools here"),
                Message(role="assistant", content="Regular response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get tool calls
    tool_calls = team_session.get_tool_calls()

    assert len(tool_calls) == 0


# Tests for get_session_messages()
def test_get_session_messages_basic(shared_db):
    """Test getting user/assistant message pairs"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="User message 1"),
                Message(role="assistant", content="Assistant response 1"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="User message 2"),
                Message(role="assistant", content="Assistant response 2"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages for session
    messages = team_session.get_messages()

    # Should get 4 messages (2 user + 2 assistant + 1 system)
    assert len(messages) == 5
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[1].content == "User message 1"
    assert messages[2].role == "assistant"
    assert messages[2].content == "Assistant response 1"
    assert messages[3].role == "user"
    assert messages[3].content == "User message 2"
    assert messages[4].role == "assistant"
    assert messages[4].content == "Assistant response 2"


def test_get_session_messages_custom_roles(shared_db):
    """Test getting messages with custom assistant roles"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="User message"),
                Message(role="model", content="Model response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages with custom assistant role
    messages = team_session.get_messages(skip_roles=["model"])

    assert len(messages) == 1
    assert messages[0].role == "user"


def test_get_session_messages_skip_history(shared_db):
    """Test that history messages are skipped"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Old user", from_history=True),
                Message(role="assistant", content="Old assistant", from_history=True),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="New user"),
                Message(role="assistant", content="New assistant"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages, skipping history
    messages = team_session.get_messages(skip_history_messages=True)

    # Should only get new messages
    assert len(messages) == 2
    assert messages[0].content == "New user"
    assert messages[1].content == "New assistant"


def test_get_session_messages_incomplete_pairs(shared_db):
    """Test handling of incomplete user/assistant pairs"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="User only"),
                # No assistant response
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="assistant", content="Assistant only"),
                # No user message
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run3",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Complete user"),
                Message(role="assistant", content="Complete assistant"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages - only complete pairs
    messages = team_session.get_messages(last_n_runs=1)

    # Should only get the complete pair from the last run
    assert len(messages) == 2
    assert messages[0].content == "Complete user"
    assert messages[1].content == "Complete assistant"


# Tests for get_session_summary()
def test_get_session_summary_exists(shared_db):
    """Test getting session summary when it exists"""
    session_id = f"test_session_{uuid.uuid4()}"

    summary = SessionSummary(
        summary="Test summary",
        topics=["topic1", "topic2"],
        updated_at=datetime.now(),
    )

    team_session = TeamSession(
        session_id=session_id,
        summary=summary,
        created_at=int(time()),
    )

    shared_db.upsert_session(session=team_session)
    retrieved_session = shared_db.get_session(session_id=session_id, session_type=SessionType.TEAM)

    # Get summary
    session_summary = retrieved_session.get_session_summary()

    assert session_summary is not None
    assert session_summary.summary == "Test summary"
    assert session_summary.topics == ["topic1", "topic2"]


def test_get_session_summary_none(shared_db):
    """Test getting session summary when it doesn't exist"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Get summary
    session_summary = team_session.get_session_summary()

    assert session_summary is None


# Tests for get_chat_history()
def test_get_chat_history_basic(shared_db):
    """Test getting chat history"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Message 1"),
                Message(role="assistant", content="Response 1"),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Message 2"),
                Message(role="assistant", content="Response 2"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history
    chat_history = team_session.get_chat_history()

    assert len(chat_history) == 4
    assert chat_history[0].content == "Message 1"
    assert chat_history[1].content == "Response 1"
    assert chat_history[2].content == "Message 2"
    assert chat_history[3].content == "Response 2"


def test_get_chat_history_skip_from_history(shared_db):
    """Test that messages marked as from_history are excluded"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Old message", from_history=True),
                Message(role="assistant", content="Old response", from_history=True),
            ],
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="New message", from_history=False),
                Message(role="assistant", content="New response", from_history=False),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history
    chat_history = team_session.get_chat_history()

    # Should only include non-history messages
    assert len(chat_history) == 2
    assert chat_history[0].content == "New message"
    assert chat_history[1].content == "New response"


def test_get_chat_history_empty(shared_db):
    """Test getting chat history from empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Get chat history
    chat_history = team_session.get_chat_history()

    assert len(chat_history) == 0


def test_get_chat_history_default_roles(shared_db):
    """Test that chat history excludes the system and tool roles by default"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System message"),
                Message(role="user", content="User message"),
                Message(role="assistant", content="Assistant message"),
                Message(role="tool", content="Tool message"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history
    chat_history = team_session.get_chat_history()

    # Assserting the messages with roles "system" and "tool" are skipped
    assert len(chat_history) == 2
    assert chat_history[0].role == "user"
    assert chat_history[1].role == "assistant"


def test_get_chat_history_skip_roles(shared_db):
    """Test skipping specific roles in chat history"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System message"),
                Message(role="user", content="User message"),
                Message(role="assistant", content="Assistant message"),
                Message(role="tool", content="Tool message"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history, skipping system and tool roles
    chat_history = team_session.get_chat_history()

    assert len(chat_history) == 2
    assert chat_history[0].role == "user"
    assert chat_history[1].role == "assistant"


def test_get_chat_history_filter_parent_run_id(shared_db):
    """Test that chat history only includes team leader runs (no parent_run_id)"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="team_run",
            status=RunStatus.completed,
            parent_run_id=None,
            messages=[
                Message(role="user", content="Team leader message"),
                Message(role="assistant", content="Team leader response"),
            ],
        ),
        RunOutput(
            run_id="member_run",
            agent_id="agent_1",
            status=RunStatus.completed,
            parent_run_id="team_run",
            messages=[
                Message(role="user", content="Member message"),
                Message(role="assistant", content="Member response"),
            ],
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history - should only include team leader runs
    chat_history = team_session.get_chat_history()

    assert len(chat_history) == 2
    assert chat_history[0].content == "Team leader message"
    assert chat_history[1].content == "Team leader response"


# Tests for get_team_history()
def test_get_team_history_basic(shared_db):
    """Test getting team history as input/response pairs"""
    session_id = f"test_session_{uuid.uuid4()}"

    from agno.run.agent import RunInput

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content="Query 1"),
            content="Response 1",
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content="Query 2"),
            content="Response 2",
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get team history
    history = team_session.get_team_history()

    assert len(history) == 2
    assert history[0] == ("Query 1", "Response 1")  # content is serialized
    assert history[1] == ("Query 2", "Response 2")


def test_get_team_history_with_num_runs(shared_db):
    """Test limiting team history to N runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    from agno.run.agent import RunInput

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id=f"run{i}",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content=f"Query {i}"),
            content=f"Response {i}",
        )
        for i in range(5)
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get only last 2 runs
    history = team_session.get_team_history(num_runs=2)

    assert len(history) == 2
    # Should get the last 2 runs
    assert history[0][0] == "Query 3"
    assert history[1][0] == "Query 4"


def test_get_team_history_only_completed_runs(shared_db):
    """Test that only completed runs are included in team history"""
    session_id = f"test_session_{uuid.uuid4()}"

    from agno.run.agent import RunInput

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content="Completed query"),
            content="Completed response",
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.running,
            parent_run_id=None,
            input=RunInput(input_content="Running query"),
            content="Running response",
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run3",
            status=RunStatus.error,
            parent_run_id=None,
            input=RunInput(input_content="Error query"),
            content="Error response",
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get team history - should only include completed runs
    history = team_session.get_team_history()

    assert len(history) == 1
    assert history[0][0] == "Completed query"


def test_get_team_history_skip_member_runs(shared_db):
    """Test that member runs (with parent_run_id) are excluded"""
    session_id = f"test_session_{uuid.uuid4()}"

    from agno.run.agent import RunInput

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="team_run",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content="Team query"),
            content="Team response",
        ),
        RunOutput(
            run_id="member_run",
            agent_id="agent_1",
            status=RunStatus.completed,
            parent_run_id="team_run",
            input=RunInput(input_content="Member query"),
            content="Member response",
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get team history - should only include team leader runs
    history = team_session.get_team_history()

    assert len(history) == 1
    assert history[0][0] == "Team query"


def test_get_team_history_empty(shared_db):
    """Test getting team history from empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Get team history
    history = team_session.get_team_history()

    assert len(history) == 0


# Tests for get_team_history_context()
def test_get_team_history_context_basic(shared_db):
    """Test getting formatted team history context"""
    session_id = f"test_session_{uuid.uuid4()}"

    from agno.run.agent import RunInput

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id="run1",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content="Query 1"),
            content="Response 1",
        ),
        TeamRunOutput(
            team_id="test_team",
            run_id="run2",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content="Query 2"),
            content="Response 2",
        ),
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get team history context
    context = team_session.get_team_history_context()

    assert context is not None
    assert "<team_history_context>" in context
    assert "</team_history_context>" in context
    assert "[run-1]" in context
    assert "[run-2]" in context
    assert "input: Query 1" in context
    assert "input: Query 2" in context
    assert "response: Response 1" in context
    assert "response: Response 2" in context


def test_get_team_history_context_with_num_runs(shared_db):
    """Test limiting team history context to N runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    from agno.run.agent import RunInput

    runs = [
        TeamRunOutput(
            team_id="test_team",
            run_id=f"run{i}",
            status=RunStatus.completed,
            parent_run_id=None,
            input=RunInput(input_content=f"Query {i}"),
            content=f"Response {i}",
        )
        for i in range(5)
    ]

    team_session = create_session_with_runs(shared_db, session_id, runs)

    # Get context for last 2 runs
    context = team_session.get_team_history_context(num_runs=2)

    assert context is not None
    # Should only have run-1 and run-2 in the context
    assert "[run-1]" in context
    assert "[run-2]" in context
    assert "[run-3]" not in context
    # Should have the last 2 queries
    assert "Query 3" in context
    assert "Query 4" in context


def test_get_team_history_context_empty(shared_db):
    """Test getting team history context from empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    team_session = create_session_with_runs(shared_db, session_id, [])

    # Get team history context
    context = team_session.get_team_history_context()

    assert context is None
