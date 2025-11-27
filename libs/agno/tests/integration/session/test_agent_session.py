"""Integration tests for AgentSession methods"""

import uuid
from datetime import datetime
from time import time

from agno.db.base import SessionType
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.session.summary import SessionSummary


def create_session_with_runs(shared_db, session_id: str, runs: list[RunOutput]) -> AgentSession:
    """Helper function to create and store a session with runs in the database"""
    agent_session = AgentSession(session_id=session_id, agent_id="test_agent", runs=runs, created_at=int(time()))

    # Store the session in the database
    shared_db.upsert_session(session=agent_session)

    # Retrieve it back to ensure it's properly persisted
    return shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)


def test_get_messages_basic(shared_db):
    """Test basic functionality of getting messages from last N runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create 3 runs with messages
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="First user message"),
                Message(role="assistant", content="First assistant response"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Second user message"),
                Message(role="assistant", content="Second assistant response"),
            ],
        ),
        RunOutput(
            run_id="run3",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Third user message"),
                Message(role="assistant", content="Third assistant response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)
    assert agent_session is not None
    assert len(agent_session.runs) == 3

    # Test getting messages from last 2 runs
    messages = agent_session.get_messages(last_n_runs=2)

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
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="First message"),
                Message(role="assistant", content="First response"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Second message"),
                Message(role="assistant", content="Second response"),
            ],
        ),
        RunOutput(
            run_id="run3",
            agent_id="test_agent",
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

    agent_session = create_session_with_runs(shared_db, session_id, runs)
    assert agent_session is not None

    # Test getting last 3 messages (should get system message + last 2 non-system messages)
    messages = agent_session.get_messages(limit=3)

    assert len(messages) == 3
    # System message should be first
    assert messages[0].role == "system"
    assert messages[0].content == "System prompt"
    # Then the last 2 non-system messages
    assert messages[1].content == "Fourth message"
    assert messages[2].content == "Fourth response"


def test_get_messages_with_limit_skip_system_message(shared_db):
    """Test getting last N messages instead of last N runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs with system messages
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="First message"),
                Message(role="assistant", content="First response"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Second message"),
                Message(role="assistant", content="Second response"),
            ],
        ),
        RunOutput(
            run_id="run3",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Third message"),
                Message(role="assistant", content="Third response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)
    assert agent_session is not None

    # Test getting last 3 messages (should get last 3 non-system messages)
    messages = agent_session.get_messages(limit=3, skip_roles=["system"])

    assert len(messages) == 3
    # Then the last 3 non-system messages
    assert messages[0].content == "Second response"
    assert messages[1].content == "Third message"
    assert messages[2].content == "Third response"


def test_get_messages_with_limit_skip_incomplete_tool_results(shared_db):
    """Test getting last N messages and skipping incomplete tool results"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs with system messages
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
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

    agent_session = create_session_with_runs(shared_db, session_id, runs)
    assert agent_session is not None

    # This will include the tool result only, but we don't want to include it without an associated assistant response with tool calls
    messages = agent_session.get_messages(limit=3, skip_roles=["system"])

    assert len(messages) == 1
    # Then the assistant response with the tool call
    assert messages[0].content == "Assistant response"

    # This will include the tool result and the assistant response with the tool call
    messages = agent_session.get_messages(limit=4, skip_roles=["system"])

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
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Old message", from_history=True),
                Message(role="assistant", content="Old response", from_history=True),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="New message", from_history=False),
                Message(role="assistant", content="New response", from_history=False),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages with skip_history_messages=True (default)
    messages = agent_session.get_messages(skip_history_messages=True)

    # Should only get messages from run2 that are not from history
    assert len(messages) == 2
    assert all(not msg.from_history for msg in messages)
    assert messages[0].content == "New message"
    assert messages[1].content == "New response"

    # Get messages with skip_history_messages=False
    messages_with_history = agent_session.get_messages(skip_history_messages=False)

    # Should get all messages including history
    assert len(messages_with_history) == 4


def test_get_messages_skip_role(shared_db):
    """Test skipping messages with specific role"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="User message"),
                Message(role="assistant", content="Assistant response"),
                Message(role="tool", content="Tool result"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Skip system messages
    messages = agent_session.get_messages(skip_roles=["system"])

    assert len(messages) == 3
    assert all(msg.role != "system" for msg in messages)

    # Skip tool messages
    messages_no_tool = agent_session.get_messages(skip_roles=["tool"])

    assert len(messages_no_tool) == 3
    assert all(msg.role != "tool" for msg in messages_no_tool)


def test_get_messages_skip_status(shared_db):
    """Test skipping runs with specific status"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs with different statuses
    runs = [
        RunOutput(
            run_id="run_completed",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Completed run"),
                Message(role="assistant", content="Completed response"),
            ],
        ),
        RunOutput(
            run_id="run_error",
            agent_id="test_agent",
            status=RunStatus.error,
            messages=[
                Message(role="user", content="Error run"),
                Message(role="assistant", content="Error response"),
            ],
        ),
        RunOutput(
            run_id="run_cancelled",
            agent_id="test_agent",
            status=RunStatus.cancelled,
            messages=[
                Message(role="user", content="Cancelled run"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # By default, should skip error, cancelled, and paused runs
    messages = agent_session.get_messages(skip_roles=["system"])

    assert len(messages) == 2  # Only messages from completed run
    assert messages[0].content == "Completed run"
    assert messages[1].content == "Completed response"

    # Explicitly skip only error status
    messages_skip_error = agent_session.get_messages(skip_statuses=[RunStatus.error])

    # Should get messages from the completed run and the cancelled run
    assert len(messages_skip_error) == 3


def test_get_messages_filter_by_agent_id(shared_db):
    """Test filtering messages by agent_id"""
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

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages only from agent_1
    messages_agent1 = agent_session.get_messages(agent_id="agent_1")

    assert len(messages_agent1) == 2
    assert messages_agent1[0].content == "Agent 1 message"
    assert messages_agent1[1].content == "Agent 1 response"

    # Get messages only from agent_2
    messages_agent2 = agent_session.get_messages(agent_id="agent_2")

    assert len(messages_agent2) == 2
    assert messages_agent2[0].content == "Agent 2 message"
    assert messages_agent2[1].content == "Agent 2 response"


def test_get_messages_system_message_handling(shared_db):
    """Test that system messages are handled correctly and only added once"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create multiple runs each with system messages
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="First message"),
                Message(role="assistant", content="First response"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="Second message"),
                Message(role="assistant", content="Second response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get all messages
    messages = agent_session.get_messages()

    # Count system messages - should only be 1
    system_messages = [msg for msg in messages if msg.role == "system"]
    assert len(system_messages) == 1

    # System message should be first
    assert messages[0].role == "system"


def test_get_messages_empty_session(shared_db):
    """Test getting messages from an empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create session with no runs
    agent_session = create_session_with_runs(shared_db, session_id, [])

    # Get messages from empty session
    messages = agent_session.get_messages()

    assert len(messages) == 0


def test_get_messages_last_n_with_multiple_runs(shared_db):
    """Test getting messages from specific number of last runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create 5 runs
    runs = [
        RunOutput(
            run_id=f"run{i}",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content=f"Message {i}"),
                Message(role="assistant", content=f"Response {i}"),
            ],
        )
        for i in range(5)
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages from last 2 runs only
    messages = agent_session.get_messages(last_n_runs=2)

    # Should have 4 messages (2 messages per run * 2 runs)
    assert len(messages) == 4

    # Verify we got the last 2 runs (runs 3 and 4)
    assert messages[0].content == "Message 3"
    assert messages[1].content == "Response 3"
    assert messages[2].content == "Message 4"
    assert messages[3].content == "Response 4"

    # Get messages from last 1 run
    messages_one_run = agent_session.get_messages(last_n_runs=1)

    # Should have 2 messages from the last run
    assert len(messages_one_run) == 2
    assert messages_one_run[0].content == "Message 4"
    assert messages_one_run[1].content == "Response 4"


def test_get_messages_with_none_messages_in_run(shared_db):
    """Test handling runs with no messages"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create run with None messages and run with valid messages
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=None,
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Valid message"),
                Message(role="assistant", content="Valid response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Should handle None messages gracefully
    messages = agent_session.get_messages()

    assert len(messages) == 2
    assert messages[0].content == "Valid message"


def test_get_messages_combined_filters(shared_db):
    """Test combining multiple filters"""
    session_id = f"test_session_{uuid.uuid4()}"

    # Create runs with various characteristics
    runs = [
        RunOutput(
            run_id="run1",
            agent_id="agent_1",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System"),
                Message(role="user", content="Agent 1 user", from_history=True),
                Message(role="assistant", content="Agent 1 assistant"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="agent_1",
            status=RunStatus.error,
            messages=[
                Message(role="user", content="Error run"),
            ],
        ),
        RunOutput(
            run_id="run3",
            agent_id="agent_1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Agent 1 new user"),
                Message(role="assistant", content="Agent 1 new assistant"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Filter by agent_id, skip error status, skip history messages, and skip system role
    messages = agent_session.get_messages(
        agent_id="agent_1",
        skip_statuses=[RunStatus.error],
        skip_history_messages=True,
        skip_roles=["system"],
    )

    # Should get messages from run1 and run3, excluding system, history, and error runs
    # From run1: only assistant message (user is history, system is skipped)
    # From run3: both user and assistant
    assert len(messages) == 3
    assert messages[0].content == "Agent 1 assistant"
    assert messages[1].content == "Agent 1 new user"
    assert messages[2].content == "Agent 1 new assistant"


# Tests for to_dict() and from_dict()
def test_to_dict_basic(shared_db):
    """Test converting AgentSession to dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Test message"),
                Message(role="assistant", content="Test response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Convert to dict
    session_dict = agent_session.to_dict()

    assert session_dict["session_id"] == session_id
    assert session_dict["agent_id"] == "test_agent"
    assert session_dict["runs"] is not None
    assert len(session_dict["runs"]) == 1
    assert session_dict["runs"][0]["run_id"] == "run1"


def test_to_dict_with_summary(shared_db):
    """Test converting AgentSession with summary to dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    summary = SessionSummary(
        summary="Test session summary",
        topics=["topic1", "topic2"],
        updated_at=datetime.now(),
    )

    agent_session = AgentSession(
        session_id=session_id,
        agent_id="test_agent",
        summary=summary,
        created_at=int(time()),
    )

    shared_db.upsert_session(session=agent_session)
    retrieved_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)

    # Convert to dict
    session_dict = retrieved_session.to_dict()

    assert session_dict["summary"] is not None
    assert session_dict["summary"]["summary"] == "Test session summary"
    assert session_dict["summary"]["topics"] == ["topic1", "topic2"]


def test_from_dict_basic(shared_db):
    """Test creating AgentSession from dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    session_data = {
        "session_id": session_id,
        "agent_id": "test_agent",
        "user_id": "test_user",
        "session_data": {"key": "value"},
        "metadata": {"meta_key": "meta_value"},
        "runs": [
            {
                "run_id": "run1",
                "agent_id": "test_agent",
                "status": RunStatus.completed,
                "messages": [
                    {"role": "user", "content": "Test message"},
                    {"role": "assistant", "content": "Test response"},
                ],
            }
        ],
    }

    # Create from dict
    agent_session = AgentSession.from_dict(session_data)

    assert agent_session is not None
    assert agent_session.session_id == session_id
    assert agent_session.agent_id == "test_agent"
    assert agent_session.user_id == "test_user"
    assert agent_session.session_data == {"key": "value"}
    assert agent_session.metadata == {"meta_key": "meta_value"}
    assert len(agent_session.runs) == 1
    assert agent_session.runs[0].run_id == "run1"


def test_from_dict_missing_session_id(shared_db):
    """Test that from_dict returns None when session_id is missing"""
    session_data = {
        "agent_id": "test_agent",
        "runs": [],
    }

    # Should return None with missing session_id
    agent_session = AgentSession.from_dict(session_data)

    assert agent_session is None


def test_from_dict_with_summary(shared_db):
    """Test creating AgentSession with summary from dictionary"""
    session_id = f"test_session_{uuid.uuid4()}"

    session_data = {
        "session_id": session_id,
        "summary": {
            "summary": "Test summary",
            "topics": ["topic1"],
            "updated_at": datetime.now().isoformat(),
        },
    }

    agent_session = AgentSession.from_dict(session_data)

    assert agent_session is not None
    assert agent_session.summary is not None
    assert agent_session.summary.summary == "Test summary"
    assert agent_session.summary.topics == ["topic1"]


# Tests for upsert_run()
def test_upsert_run_add_new(shared_db):
    """Test adding a new run to session"""
    session_id = f"test_session_{uuid.uuid4()}"

    agent_session = create_session_with_runs(shared_db, session_id, [])

    # Add a new run
    new_run = RunOutput(
        run_id="run1",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="New message"),
            Message(role="assistant", content="New response"),
        ],
    )

    agent_session.upsert_run(new_run)

    assert len(agent_session.runs) == 1
    assert agent_session.runs[0].run_id == "run1"


def test_upsert_run_update_existing(shared_db):
    """Test updating an existing run"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Original message"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Update existing run
    updated_run = RunOutput(
        run_id="run1",
        agent_id="test_agent",
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Updated message"),
            Message(role="assistant", content="Updated response"),
        ],
    )

    agent_session.upsert_run(updated_run)

    # Should still have only 1 run, but with updated content
    assert len(agent_session.runs) == 1
    assert agent_session.runs[0].run_id == "run1"
    assert len(agent_session.runs[0].messages) == 2
    assert agent_session.runs[0].messages[0].content == "Updated message"


def test_upsert_run_multiple(shared_db):
    """Test adding multiple runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    agent_session = create_session_with_runs(shared_db, session_id, [])

    # Add multiple runs
    for i in range(3):
        run = RunOutput(
            run_id=f"run{i}",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content=f"Message {i}"),
            ],
        )
        agent_session.upsert_run(run)

    assert len(agent_session.runs) == 3
    assert agent_session.runs[0].run_id == "run0"
    assert agent_session.runs[1].run_id == "run1"
    assert agent_session.runs[2].run_id == "run2"


# Tests for get_run()
def test_get_run_exists(shared_db):
    """Test retrieving an existing run"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[Message(role="user", content="Message 1")],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[Message(role="user", content="Message 2")],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get specific run
    run = agent_session.get_run("run2")

    assert run is not None
    assert run.run_id == "run2"
    assert run.messages[0].content == "Message 2"


def test_get_run_not_exists(shared_db):
    """Test retrieving a non-existent run"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[Message(role="user", content="Message 1")],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Try to get non-existent run
    run = agent_session.get_run("non_existent")

    assert run is None


def test_get_run_empty_session(shared_db):
    """Test retrieving run from empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    agent_session = create_session_with_runs(shared_db, session_id, [])

    # Try to get run from empty session
    run = agent_session.get_run("run1")

    assert run is None


# Tests for get_tool_calls()
def test_get_tool_calls_basic(shared_db):
    """Test retrieving tool calls from messages"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
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

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get tool calls
    tool_calls = agent_session.get_tool_calls()

    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call1"
    assert tool_calls[0]["function"]["name"] == "search"


def test_get_tool_calls_multiple_runs(shared_db):
    """Test retrieving tool calls from multiple runs"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(
                    role="assistant",
                    tool_calls=[{"id": "call1", "type": "function"}],
                ),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
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

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get all tool calls (should be in reverse order - most recent first)
    tool_calls = agent_session.get_tool_calls()

    assert len(tool_calls) == 3
    # Should be reversed (run2 before run1)
    assert tool_calls[0]["id"] == "call2"
    assert tool_calls[1]["id"] == "call3"
    assert tool_calls[2]["id"] == "call1"


def test_get_tool_calls_with_limit(shared_db):
    """Test retrieving limited number of tool calls"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
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

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get only 2 tool calls
    tool_calls = agent_session.get_tool_calls(num_calls=2)

    assert len(tool_calls) == 2
    assert tool_calls[0]["id"] == "call1"
    assert tool_calls[1]["id"] == "call2"


def test_get_tool_calls_no_tools(shared_db):
    """Test retrieving tool calls when there are none"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="No tools here"),
                Message(role="assistant", content="Regular response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get tool calls
    tool_calls = agent_session.get_tool_calls()

    assert len(tool_calls) == 0


# Tests for get_session_messages()


def test_get_session_messages_basic(shared_db):
    """Test getting user/assistant message pairs"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System prompt"),
                Message(role="user", content="User message 1"),
                Message(role="assistant", content="Assistant response 1"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="User message 2"),
                Message(role="assistant", content="Assistant response 2"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages for session
    messages = agent_session.get_messages()

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
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="User message"),
                Message(role="model", content="Model response"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages with custom assistant role
    messages = agent_session.get_messages()

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "model"


def test_get_session_messages_skip_history(shared_db):
    """Test that history messages are skipped"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Old user", from_history=True),
                Message(role="assistant", content="Old assistant", from_history=True),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="New user"),
                Message(role="assistant", content="New assistant"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get messages, skipping history
    messages = agent_session.get_messages(skip_history_messages=True)

    # Should only get new messages
    assert len(messages) == 2
    assert messages[0].content == "New user"
    assert messages[1].content == "New assistant"


# Tests for get_session_summary()
def test_get_session_summary_exists(shared_db):
    """Test getting session summary when it exists"""
    session_id = f"test_session_{uuid.uuid4()}"

    summary = SessionSummary(
        summary="Test summary",
        topics=["topic1", "topic2"],
        updated_at=datetime.now(),
    )

    agent_session = AgentSession(
        session_id=session_id,
        summary=summary,
        created_at=int(time()),
    )

    shared_db.upsert_session(session=agent_session)
    retrieved_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)

    # Get summary
    session_summary = retrieved_session.get_session_summary()

    assert session_summary is not None
    assert session_summary.summary == "Test summary"
    assert session_summary.topics == ["topic1", "topic2"]


def test_get_session_summary_none(shared_db):
    """Test getting session summary when it doesn't exist"""
    session_id = f"test_session_{uuid.uuid4()}"

    agent_session = create_session_with_runs(shared_db, session_id, [])

    # Get summary
    session_summary = agent_session.get_session_summary()

    assert session_summary is None


# Tests for get_chat_history()
def test_get_chat_history_basic(shared_db):
    """Test getting chat history"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Message 1"),
                Message(role="assistant", content="Response 1"),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Message 2"),
                Message(role="assistant", content="Response 2"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history
    chat_history = agent_session.get_chat_history()

    assert len(chat_history) == 4
    assert chat_history[0].content == "Message 1"
    assert chat_history[1].content == "Response 1"
    assert chat_history[2].content == "Message 2"
    assert chat_history[3].content == "Response 2"


def test_get_chat_history_skip_from_history(shared_db):
    """Test that messages marked as from_history are excluded"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Old message", from_history=True),
                Message(role="assistant", content="Old response", from_history=True),
            ],
        ),
        RunOutput(
            run_id="run2",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="New message", from_history=False),
                Message(role="assistant", content="New response", from_history=False),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history
    chat_history = agent_session.get_chat_history()

    # Should only include non-history messages
    assert len(chat_history) == 2
    assert chat_history[0].content == "New message"
    assert chat_history[1].content == "New response"


def test_get_chat_history_empty(shared_db):
    """Test getting chat history from empty session"""
    session_id = f"test_session_{uuid.uuid4()}"

    agent_session = create_session_with_runs(shared_db, session_id, [])

    # Get chat history
    chat_history = agent_session.get_chat_history()

    assert len(chat_history) == 0


def test_get_chat_history_default_roles(shared_db):
    """Test that chat history excludes the system and tool roles by default"""
    session_id = f"test_session_{uuid.uuid4()}"

    runs = [
        RunOutput(
            run_id="run1",
            agent_id="test_agent",
            status=RunStatus.completed,
            messages=[
                Message(role="system", content="System message"),
                Message(role="user", content="User message"),
                Message(role="assistant", content="Assistant message"),
                Message(role="tool", content="Tool message"),
            ],
        ),
    ]

    agent_session = create_session_with_runs(shared_db, session_id, runs)

    # Get chat history - should include all roles
    chat_history = agent_session.get_chat_history()

    assert len(chat_history) == 2
    assert chat_history[0].role == "user"
    assert chat_history[1].role == "assistant"
