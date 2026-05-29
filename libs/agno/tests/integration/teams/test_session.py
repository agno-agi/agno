import uuid
from typing import Any, Dict, Optional

import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run.team import TeamRunEvent
from agno.team.team import Team


def team_factory(shared_db, session_id: Optional[str] = None, session_state: Optional[Dict[str, Any]] = None):
    return Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        session_id=session_id,
        session_state=session_state,
        members=[],
        db=shared_db,
        update_memory_on_run=True,
        markdown=True,
        telemetry=False,
    )


def test_team_set_session_name(shared_db):
    session_id = "session_1"
    session_state = {"test_key": "test_value"}

    team = team_factory(shared_db, session_id, session_state)

    team.run("Hello, how are you?")

    team.set_session_name(session_id=session_id, session_name="my_test_session")

    session_from_storage = team.get_session(session_id=session_id)
    assert session_from_storage is not None
    assert session_from_storage.session_id == session_id
    assert session_from_storage.session_data is not None
    assert session_from_storage.session_data["session_name"] == "my_test_session"


def test_team_get_session_name(shared_db):
    session_id = "session_1"
    team = team_factory(shared_db, session_id)
    team.run("Hello, how are you?")
    team.set_session_name(session_id=session_id, session_name="my_test_session")
    assert team.get_session_name() == "my_test_session"


def test_team_get_session_state(shared_db):
    session_id = "session_1"
    team = team_factory(shared_db, session_id, session_state={"test_key": "test_value"})
    team.run("Hello, how are you?")
    assert team.get_session_state() == {"test_key": "test_value"}


def test_team_get_session_metrics(shared_db):
    session_id = "session_1"
    team = team_factory(shared_db, session_id)
    team.run("Hello, how are you?")
    metrics = team.get_session_metrics()
    assert metrics is not None
    assert metrics.total_tokens > 0
    assert metrics.input_tokens > 0
    assert metrics.output_tokens > 0
    assert metrics.total_tokens == metrics.input_tokens + metrics.output_tokens


# Async database tests
@pytest.mark.asyncio
async def test_async_run_with_async_db(async_shared_db):
    """Test Team async arun() with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    response = await team.arun("Hello team", session_id=session_id)
    assert response is not None
    assert response.content is not None


@pytest.mark.asyncio
async def test_async_run_stream_with_async_db(async_shared_db):
    """Test Team async arun() streaming with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    final_response = None
    async for response in team.arun("Hello team", session_id=session_id, stream=True):
        final_response = response

    assert final_response is not None
    assert final_response.content is not None


@pytest.mark.asyncio
async def test_async_run_stream_events_with_async_db(async_shared_db):
    """Test Team async arun() with stream_events=True and async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())

    events = {}
    async for run_response_delta in team.arun("Hello team", session_id=session_id, stream=True, stream_events=True):
        if run_response_delta.event not in events:
            events[run_response_delta.event] = []
        events[run_response_delta.event].append(run_response_delta)

    assert TeamRunEvent.run_completed in events
    assert len(events[TeamRunEvent.run_completed]) == 1
    assert events[TeamRunEvent.run_completed][0].content is not None


@pytest.mark.asyncio
async def test_aget_session_with_async_db(async_shared_db):
    """Test aget_session with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)

    session = await team.aget_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs) == 1


@pytest.mark.asyncio
async def test_asave_session_with_async_db(async_shared_db):
    """Test asave_session with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)

    session = await team.aget_session(session_id=session_id)
    session.session_data["custom_key"] = "custom_value"

    await team.asave_session(session)

    retrieved_session = await team.aget_session(session_id=session_id)
    assert retrieved_session.session_data["custom_key"] == "custom_value"


@pytest.mark.asyncio
async def test_aget_last_run_output_with_async_db(async_shared_db):
    """Test aget_last_run_output with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("First message", session_id=session_id)
    response2 = await team.arun("Second message", session_id=session_id)

    last_output = await team.aget_last_run_output(session_id=session_id)
    assert last_output is not None
    assert last_output.run_id == response2.run_id


@pytest.mark.asyncio
async def test_aget_run_output_with_async_db(async_shared_db):
    """Test aget_run_output with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    response = await team.arun("Hello", session_id=session_id)
    run_id = response.run_id

    retrieved_output = await team.aget_run_output(run_id=run_id, session_id=session_id)
    assert retrieved_output is not None
    assert retrieved_output.run_id == run_id


@pytest.mark.asyncio
async def test_aget_chat_history_with_async_db(async_shared_db):
    """Test aget_chat_history with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)
    await team.arun("How are you?", session_id=session_id)

    chat_history = await team.aget_chat_history(session_id=session_id)
    assert len(chat_history) >= 4


@pytest.mark.asyncio
async def test_aget_session_messages_with_async_db(async_shared_db):
    """Test aget_session_messages with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)
    await team.arun("How are you?", session_id=session_id)

    messages = await team.aget_session_messages(session_id=session_id)
    assert len(messages) >= 4


@pytest.mark.asyncio
async def test_aget_session_state_with_async_db(async_shared_db):
    """Test aget_session_state with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())

    await team.arun("Hello", session_id=session_id, session_state={"counter": 5, "name": "test"})

    state = await team.aget_session_state(session_id=session_id)
    assert state == {"counter": 5, "name": "test"}


@pytest.mark.asyncio
async def test_aupdate_session_state_with_async_db(async_shared_db):
    """Test aupdate_session_state with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())

    await team.arun("Hello", session_id=session_id, session_state={"counter": 0, "items": []})

    result = await team.aupdate_session_state({"counter": 10}, session_id=session_id)
    assert result == {"counter": 10, "items": []}

    updated_state = await team.aget_session_state(session_id=session_id)
    assert updated_state["counter"] == 10


@pytest.mark.asyncio
async def test_aget_session_name_with_async_db(async_shared_db):
    """Test aget_session_name with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)
    await team.aset_session_name(session_id=session_id, session_name="Async Session")

    name = await team.aget_session_name(session_id=session_id)
    assert name == "Async Session"


@pytest.mark.asyncio
async def test_aset_session_name_with_async_db(async_shared_db):
    """Test aset_session_name with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)

    updated_session = await team.aset_session_name(session_id=session_id, session_name="Test Session")
    assert updated_session.session_data["session_name"] == "Test Session"


@pytest.mark.asyncio
async def test_aget_session_metrics_with_async_db(async_shared_db):
    """Test aget_session_metrics with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)

    metrics = await team.aget_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_adelete_session_with_async_db(async_shared_db):
    """Test adelete_session with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)

    # Verify session exists
    session = await team.aget_session(session_id=session_id)
    assert session is not None

    # Delete session
    await team.adelete_session(session_id=session_id)

    # Verify session is deleted
    session = await team.aget_session(session_id=session_id)
    assert session is None


@pytest.mark.asyncio
async def test_aget_session_summary_with_async_db(async_shared_db):
    """Test aget_session_summary with async database."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())
    await team.arun("Hello", session_id=session_id)

    summary = await team.aget_session_summary(session_id=session_id)
    assert summary is None  # Summaries not enabled by default


@pytest.mark.asyncio
async def test_session_persistence_across_async_runs(async_shared_db):
    """Test that session persists correctly across different async run types."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())

    # Async run
    await team.arun("First message", session_id=session_id)

    # Async streaming run
    async for response in team.arun("Second message", session_id=session_id, stream=True):
        pass

    # Async run again
    await team.arun("Third message", session_id=session_id)

    # Verify all runs are in session
    session = await team.aget_session(session_id=session_id)
    assert session is not None
    assert len(session.runs) == 3


@pytest.mark.asyncio
async def test_team_with_multiple_members_async_db(async_shared_db):
    """Test team with multiple members using async database."""
    agent1 = Agent(
        name="Agent 1",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are helpful agent 1.",
    )
    agent2 = Agent(
        name="Agent 2",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are helpful agent 2.",
    )

    team = Team(
        members=[agent1, agent2],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
    )

    session_id = str(uuid.uuid4())
    response = await team.arun("Hello team", session_id=session_id)
    assert response is not None

    # Test async convenience functions work with multi-member team
    session = await team.aget_session(session_id=session_id)
    assert session is not None
    assert len(session.runs) == 1

    metrics = await team.aget_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_async_session_state_persistence(async_shared_db):
    """Test async session state persists across multiple runs."""
    agent1 = Agent(
        name="Agent1",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    team = Team(
        name="TestTeam",
        members=[agent1],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )

    session_id = str(uuid.uuid4())

    # First run
    await team.arun("Hello", session_id=session_id, session_state={"counter": 0})
    await team.aupdate_session_state({"counter": 1}, session_id=session_id)

    # Second run - state should persist
    await team.arun("Hi again", session_id=session_id)
    state = await team.aget_session_state(session_id=session_id)
    assert state["counter"] == 1
