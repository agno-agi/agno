import uuid

import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run import RunContext
from agno.team.team import Team


@pytest.fixture
def simple_agent():
    """Create a simple agent for team members."""
    return Agent(
        name="Helper Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are a helpful assistant.",
    )


@pytest.fixture
def test_team(shared_db, simple_agent):
    """Create a test team with database."""
    return Team(
        members=[simple_agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        markdown=True,
    )


@pytest.fixture
def async_test_team(async_shared_db, simple_agent):
    """Create a test team with async database."""
    return Team(
        members=[simple_agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )


# Tests for get_session() and aget_session()
def test_get_session(test_team):
    """Test get_session returns the correct session."""
    session_id = str(uuid.uuid4())
    response = test_team.run("Hello", session_id=session_id)
    assert response is not None

    session = test_team.get_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs) == 1


def test_get_session_with_default_session_id(test_team):
    """Test get_session uses team's session_id if not provided."""
    test_team.session_id = str(uuid.uuid4())
    response = test_team.run("Hello")
    assert response is not None

    session = test_team.get_session()
    assert session is not None
    assert session.session_id == test_team.session_id


def test_get_session_nonexistent(test_team):
    """Test get_session returns None for non-existent session."""
    session = test_team.get_session(session_id="nonexistent")
    assert session is None


@pytest.mark.asyncio
async def test_aget_session(async_test_team):
    """Test aget_session returns the correct session."""
    session_id = str(uuid.uuid4())
    response = await async_test_team.arun("Hello", session_id=session_id)
    assert response is not None

    session = await async_test_team.aget_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs) == 1


# Tests for save_session() and asave_session()
def test_save_session(test_team):
    """Test save_session updates session in database."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    session = test_team.get_session(session_id=session_id)
    session.session_data["custom_key"] = "custom_value"

    test_team.save_session(session)

    retrieved_session = test_team.get_session(session_id=session_id)
    assert retrieved_session.session_data["custom_key"] == "custom_value"


@pytest.mark.asyncio
async def test_asave_session(async_test_team):
    """Test asave_session updates session in database."""
    session_id = str(uuid.uuid4())
    await async_test_team.arun("Hello", session_id=session_id)

    session = await async_test_team.aget_session(session_id=session_id)
    session.session_data["custom_key"] = "custom_value"

    await async_test_team.asave_session(session)

    retrieved_session = await async_test_team.aget_session(session_id=session_id)
    assert retrieved_session.session_data["custom_key"] == "custom_value"


# Tests for get_chat_history()
def test_get_chat_history(test_team):
    """Test get_chat_history returns messages."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)
    test_team.run("How are you?", session_id=session_id)

    chat_history = test_team.get_chat_history(session_id=session_id)
    assert len(chat_history) >= 4  # At least 2 user messages and 2 assistant messages


def test_get_chat_history_with_default_session_id(test_team):
    """Test get_chat_history uses team's session_id if not provided."""
    test_team.session_id = str(uuid.uuid4())
    test_team.run("Hello")
    test_team.run("How are you?")

    chat_history = test_team.get_chat_history()
    assert len(chat_history) >= 4


# Tests for get_session_messages()
def test_get_session_messages(test_team):
    """Test get_session_messages returns all messages."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)
    test_team.run("How are you?", session_id=session_id)

    messages = test_team.get_session_messages(session_id=session_id)
    assert len(messages) >= 4


# Tests for get_session_name(), aget_session_name(), set_session_name(), aset_session_name()
def test_set_session_name(test_team):
    """Test set_session_name updates session name."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    updated_session = test_team.set_session_name(session_id=session_id, session_name="Test Session")
    assert updated_session.session_data["session_name"] == "Test Session"

    # Verify it's persisted
    name = test_team.get_session_name(session_id=session_id)
    assert name == "Test Session"


def test_set_session_name_autogenerate(test_team):
    """Test set_session_name with autogenerate."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    updated_session = test_team.set_session_name(session_id=session_id, autogenerate=True)
    name = updated_session.session_data.get("session_name")
    assert name is not None
    assert len(name) > 0


def test_get_session_name(test_team):
    """Test get_session_name returns the session name."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)
    test_team.set_session_name(session_id=session_id, session_name="My Session")

    name = test_team.get_session_name(session_id=session_id)
    assert name == "My Session"


@pytest.mark.asyncio
async def test_aset_session_name(async_test_team):
    """Test aset_session_name updates session name."""
    session_id = str(uuid.uuid4())
    await async_test_team.arun("Hello", session_id=session_id)

    updated_session = await async_test_team.aset_session_name(session_id=session_id, session_name="Async Test Session")
    assert updated_session.session_data["session_name"] == "Async Test Session"


@pytest.mark.asyncio
async def test_aget_session_name(async_test_team):
    """Test aget_session_name returns the session name."""
    session_id = str(uuid.uuid4())
    await async_test_team.arun("Hello", session_id=session_id)
    await async_test_team.aset_session_name(session_id=session_id, session_name="Async Session")

    name = await async_test_team.aget_session_name(session_id=session_id)
    assert name == "Async Session"


# Tests for get_session_state(), aget_session_state(), update_session_state(), aupdate_session_state()
def test_get_session_state(test_team):
    """Test get_session_state returns the session state."""
    session_id = str(uuid.uuid4())
    session_state = {"counter": 0, "items": []}
    test_team.run("Hello", session_id=session_id, session_state=session_state)

    state = test_team.get_session_state(session_id=session_id)
    assert state == {"counter": 0, "items": []}


def test_get_session_state_empty(test_team):
    """Test get_session_state returns empty dict if no state."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    state = test_team.get_session_state(session_id=session_id)
    assert state == {}


@pytest.mark.asyncio
async def test_aget_session_state(async_test_team):
    """Test aget_session_state returns the session state."""
    session_id = str(uuid.uuid4())
    session_state = {"counter": 5, "name": "test"}
    await async_test_team.arun("Hello", session_id=session_id, session_state=session_state)

    state = await async_test_team.aget_session_state(session_id=session_id)
    assert state == {"counter": 5, "name": "test"}


def test_update_session_state(test_team):
    """Test update_session_state merges updates."""
    session_id = str(uuid.uuid4())
    initial_state = {"counter": 0, "items": []}
    test_team.run("Hello", session_id=session_id, session_state=initial_state)

    result = test_team.update_session_state({"counter": 5, "new_key": "value"}, session_id=session_id)
    assert result == {"counter": 5, "new_key": "value", "items": []}

    updated_state = test_team.get_session_state(session_id=session_id)
    assert updated_state["counter"] == 5
    assert updated_state["new_key"] == "value"
    assert "items" in updated_state  # Original key should still exist


@pytest.mark.asyncio
async def test_aupdate_session_state(async_test_team):
    """Test aupdate_session_state merges updates."""
    session_id = str(uuid.uuid4())
    initial_state = {"counter": 0, "items": []}
    await async_test_team.arun("Hello", session_id=session_id, session_state=initial_state)

    result = await async_test_team.aupdate_session_state({"counter": 10}, session_id=session_id)
    assert result == {"counter": 10, "items": []}

    updated_state = await async_test_team.aget_session_state(session_id=session_id)
    assert updated_state["counter"] == 10


# Tests for get_session_metrics() and aget_session_metrics()
def test_get_session_metrics(test_team):
    """Test get_session_metrics returns metrics."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    metrics = test_team.get_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0
    assert metrics.input_tokens > 0
    assert metrics.output_tokens > 0


def test_get_session_metrics_multiple_runs(test_team):
    """Test get_session_metrics accumulates across runs."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)
    test_team.run("How are you?", session_id=session_id)

    metrics = test_team.get_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_aget_session_metrics(async_test_team):
    """Test aget_session_metrics returns metrics."""
    session_id = str(uuid.uuid4())
    await async_test_team.arun("Hello", session_id=session_id)

    metrics = await async_test_team.aget_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


# Tests for get_run_output(), aget_run_output(), get_last_run_output(), aget_last_run_output()
def test_get_run_output(test_team):
    """Test get_run_output returns specific run."""
    session_id = str(uuid.uuid4())
    response = test_team.run("Hello", session_id=session_id)
    run_id = response.run_id

    retrieved_output = test_team.get_run_output(run_id=run_id, session_id=session_id)
    assert retrieved_output is not None
    assert retrieved_output.run_id == run_id
    assert retrieved_output.content == response.content


def test_get_run_output_without_session_id(test_team):
    """Test get_run_output works without session_id if team has one."""
    test_team.session_id = str(uuid.uuid4())
    response = test_team.run("Hello")
    run_id = response.run_id

    retrieved_output = test_team.get_run_output(run_id=run_id)
    assert retrieved_output is not None
    assert retrieved_output.run_id == run_id


@pytest.mark.asyncio
async def test_aget_run_output(async_test_team):
    """Test aget_run_output returns specific run."""
    session_id = str(uuid.uuid4())
    response = await async_test_team.arun("Hello", session_id=session_id)
    run_id = response.run_id

    retrieved_output = await async_test_team.aget_run_output(run_id=run_id, session_id=session_id)
    assert retrieved_output is not None
    assert retrieved_output.run_id == run_id


def test_get_last_run_output(test_team):
    """Test get_last_run_output returns the most recent run."""
    session_id = str(uuid.uuid4())
    test_team.run("First message", session_id=session_id)
    response2 = test_team.run("Second message", session_id=session_id)

    last_output = test_team.get_last_run_output(session_id=session_id)
    assert last_output is not None
    assert last_output.run_id == response2.run_id


def test_get_last_run_output_with_default_session_id(test_team):
    """Test get_last_run_output uses team's session_id."""
    test_team.session_id = str(uuid.uuid4())
    response = test_team.run("Hello")

    last_output = test_team.get_last_run_output()
    assert last_output is not None
    assert last_output.run_id == response.run_id


@pytest.mark.asyncio
async def test_aget_last_run_output(async_test_team):
    """Test aget_last_run_output returns the most recent run."""
    session_id = str(uuid.uuid4())
    await async_test_team.arun("First message", session_id=session_id)
    response2 = await async_test_team.arun("Second message", session_id=session_id)

    last_output = await async_test_team.aget_last_run_output(session_id=session_id)
    assert last_output is not None
    assert last_output.run_id == response2.run_id


# Tests for delete_session()
def test_delete_session(test_team):
    """Test delete_session removes a session."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    # Verify session exists
    session = test_team.get_session(session_id=session_id)
    assert session is not None

    # Delete session
    test_team.delete_session(session_id=session_id)

    # Verify session is deleted
    session = test_team.get_session(session_id=session_id)
    assert session is None


# Tests for get_session_summary() and aget_session_summary()
def test_get_session_summary(test_team):
    """Test get_session_summary returns None when summaries not enabled."""
    session_id = str(uuid.uuid4())
    test_team.run("Hello", session_id=session_id)

    summary = test_team.get_session_summary(session_id=session_id)
    assert summary is None  # Summaries not enabled by default


@pytest.mark.asyncio
async def test_aget_session_summary(async_test_team):
    """Test aget_session_summary returns None when summaries not enabled."""
    session_id = str(uuid.uuid4())
    await async_test_team.arun("Hello", session_id=session_id)

    summary = await async_test_team.aget_session_summary(session_id=session_id)
    assert summary is None  # Summaries not enabled by default


# Test error handling and edge cases
def test_convenience_functions_without_db():
    """Test convenience functions fail gracefully without a database."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
    team = Team(members=[agent], model=OpenAIChat(id="gpt-4o-mini"))

    with pytest.raises(Exception):
        team.get_chat_history(session_id="test")
    with pytest.raises(Exception):
        team.get_session_name(session_id="test")
    with pytest.raises(Exception):
        team.get_session_state(session_id="test")


def test_get_session_state_with_tool_updates(test_team):
    """Test session state updates via tools."""

    def add_item(run_context: RunContext, item: str) -> str:
        """Add an item to the list."""
        run_context.session_state["items"].append(item)
        return f"Added {item}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[add_item],
    )

    team = Team(
        members=[agent],
        model=OpenAIChat(id="gpt-4o-mini"),
        db=test_team.db,
        session_state={"items": []},
    )

    session_id = str(uuid.uuid4())
    team.run("Add apple to the list", session_id=session_id)

    state = team.get_session_state(session_id=session_id)
    assert "items" in state


def test_multiple_sessions_isolation(test_team):
    """Test that multiple sessions are properly isolated."""
    session_1 = str(uuid.uuid4())
    session_2 = str(uuid.uuid4())

    # Create two separate sessions
    test_team.run("Hello from session 1", session_id=session_1, session_state={"id": 1})
    test_team.run("Hello from session 2", session_id=session_2, session_state={"id": 2})

    # Verify they are independent
    state_1 = test_team.get_session_state(session_id=session_1)
    state_2 = test_team.get_session_state(session_id=session_2)

    assert state_1["id"] == 1
    assert state_2["id"] == 2

    history_1 = test_team.get_chat_history(session_id=session_1)
    history_2 = test_team.get_chat_history(session_id=session_2)

    # Check that histories are different
    assert any("session 1" in msg.content for msg in history_1)
    assert any("session 2" in msg.content for msg in history_2)


def test_team_with_multiple_members(shared_db):
    """Test team convenience functions with multiple members."""
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
        db=shared_db,
    )

    session_id = str(uuid.uuid4())
    response = team.run("Hello team", session_id=session_id)
    assert response is not None

    # Test convenience functions work with multi-member team
    session = team.get_session(session_id=session_id)
    assert session is not None
    assert len(session.runs) == 1

    metrics = team.get_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_async_team_with_multiple_members(async_shared_db):
    """Test async team convenience functions with multiple members."""
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


def test_session_state_persistence(test_team):
    """Test session state persists across multiple runs."""
    session_id = str(uuid.uuid4())
    initial_state = {"counter": 0}

    # First run
    test_team.run("Hello", session_id=session_id, session_state=initial_state)
    test_team.update_session_state({"counter": 1}, session_id=session_id)

    # Second run - state should persist
    test_team.run("Hi again", session_id=session_id)
    state = test_team.get_session_state(session_id=session_id)
    assert state["counter"] == 1


@pytest.mark.asyncio
async def test_async_session_state_persistence(async_test_team):
    """Test async session state persists across multiple runs."""
    session_id = str(uuid.uuid4())
    initial_state = {"counter": 0}

    # First run
    await async_test_team.arun("Hello", session_id=session_id, session_state=initial_state)
    await async_test_team.aupdate_session_state({"counter": 1}, session_id=session_id)

    # Second run - state should persist
    await async_test_team.arun("Hi again", session_id=session_id)
    state = await async_test_team.aget_session_state(session_id=session_id)
    assert state["counter"] == 1
