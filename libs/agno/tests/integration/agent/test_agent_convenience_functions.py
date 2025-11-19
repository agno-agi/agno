import uuid

import pytest

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.run import RunContext


@pytest.fixture
def test_agent(shared_db):
    """Create a test agent with database."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        markdown=True,
    )


@pytest.fixture
def async_test_agent(async_shared_db):
    """Create a test agent with async database."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=async_shared_db,
        markdown=True,
    )


# Tests for get_session() and aget_session()
def test_get_session(test_agent):
    """Test get_session returns the correct session."""
    session_id = str(uuid.uuid4())
    response = test_agent.run("Hello", session_id=session_id)
    assert response is not None

    session = test_agent.get_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs) == 1


def test_get_session_with_default_session_id(test_agent):
    """Test get_session uses agent's session_id if not provided."""
    test_agent.session_id = str(uuid.uuid4())
    response = test_agent.run("Hello")
    assert response is not None

    session = test_agent.get_session()
    assert session is not None
    assert session.session_id == test_agent.session_id


def test_get_session_nonexistent(test_agent):
    """Test get_session returns None for non-existent session."""
    session = test_agent.get_session(session_id="nonexistent")
    assert session is None


@pytest.mark.asyncio
async def test_aget_session(async_test_agent):
    """Test aget_session returns the correct session."""
    session_id = str(uuid.uuid4())
    response = await async_test_agent.arun("Hello", session_id=session_id)
    assert response is not None

    session = await async_test_agent.aget_session(session_id=session_id)
    assert session is not None
    assert session.session_id == session_id
    assert len(session.runs) == 1


# Tests for save_session() and asave_session()
def test_save_session(test_agent):
    """Test save_session updates session in database."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)

    session = test_agent.get_session(session_id=session_id)
    session.session_data["custom_key"] = "custom_value"

    test_agent.save_session(session)

    retrieved_session = test_agent.get_session(session_id=session_id)
    assert retrieved_session.session_data["custom_key"] == "custom_value"


@pytest.mark.asyncio
async def test_asave_session(async_test_agent):
    """Test asave_session updates session in database."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)

    session = await async_test_agent.aget_session(session_id=session_id)
    session.session_data["custom_key"] = "custom_value"

    await async_test_agent.asave_session(session)

    retrieved_session = await async_test_agent.aget_session(session_id=session_id)
    assert retrieved_session.session_data["custom_key"] == "custom_value"


# Tests for get_chat_history() and aget_chat_history()
def test_get_chat_history(test_agent):
    """Test get_chat_history returns messages."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)
    test_agent.run("How are you?", session_id=session_id)

    chat_history = test_agent.get_chat_history(session_id=session_id)
    assert len(chat_history) >= 4  # At least 2 user messages and 2 assistant messages


def test_get_chat_history_with_default_session_id(test_agent):
    """Test get_chat_history uses agent's session_id if not provided."""
    test_agent.session_id = str(uuid.uuid4())
    test_agent.run("Hello")
    test_agent.run("How are you?")

    chat_history = test_agent.get_chat_history()
    assert len(chat_history) >= 4


@pytest.mark.asyncio
async def test_aget_chat_history(async_test_agent):
    """Test aget_chat_history returns messages."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)
    await async_test_agent.arun("How are you?", session_id=session_id)

    chat_history = await async_test_agent.aget_chat_history(session_id=session_id)
    assert len(chat_history) >= 4


# Tests for get_session_messages() and aget_session_messages()


def test_get_session_messages(test_agent):
    """Test get_session_messages returns all messages."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)
    test_agent.run("How are you?", session_id=session_id)

    messages = test_agent.get_session_messages(session_id=session_id)
    assert len(messages) >= 4


@pytest.mark.asyncio
async def test_aget_session_messages(async_test_agent):
    """Test aget_session_messages returns all messages."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)
    await async_test_agent.arun("How are you?", session_id=session_id)

    messages = await async_test_agent.aget_session_messages(session_id=session_id)
    assert len(messages) >= 4


# Tests for get_session_name(), aget_session_name(), set_session_name(), aset_session_name()
def test_set_session_name(test_agent):
    """Test set_session_name updates session name."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)

    updated_session = test_agent.set_session_name(session_id=session_id, session_name="Test Session")
    assert updated_session.session_data["session_name"] == "Test Session"

    # Verify it's persisted
    name = test_agent.get_session_name(session_id=session_id)
    assert name == "Test Session"


def test_set_session_name_autogenerate(test_agent):
    """Test set_session_name with autogenerate."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)

    updated_session = test_agent.set_session_name(session_id=session_id, autogenerate=True)
    name = updated_session.session_data.get("session_name")
    assert name is not None
    assert len(name) > 0


def test_get_session_name(test_agent):
    """Test get_session_name returns the session name."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)
    test_agent.set_session_name(session_id=session_id, session_name="My Session")

    name = test_agent.get_session_name(session_id=session_id)
    assert name == "My Session"


@pytest.mark.asyncio
async def test_aset_session_name(async_test_agent):
    """Test aset_session_name updates session name."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)

    updated_session = await async_test_agent.aset_session_name(session_id=session_id, session_name="Async Test Session")
    assert updated_session.session_data["session_name"] == "Async Test Session"


@pytest.mark.asyncio
async def test_aget_session_name(async_test_agent):
    """Test aget_session_name returns the session name."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)
    await async_test_agent.aset_session_name(session_id=session_id, session_name="Async Session")

    name = await async_test_agent.aget_session_name(session_id=session_id)
    assert name == "Async Session"


# Tests for get_session_state(), aget_session_state(), update_session_state(), aupdate_session_state()
def test_get_session_state(test_agent):
    """Test get_session_state returns the session state."""
    session_id = str(uuid.uuid4())
    session_state = {"counter": 0, "items": []}
    test_agent.run("Hello", session_id=session_id, session_state=session_state)

    state = test_agent.get_session_state(session_id=session_id)
    assert state == {"counter": 0, "items": []}


def test_get_session_state_empty(test_agent):
    """Test get_session_state returns empty dict if no state."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)

    state = test_agent.get_session_state(session_id=session_id)
    assert state == {}


@pytest.mark.asyncio
async def test_aget_session_state(async_test_agent):
    """Test aget_session_state returns the session state."""
    session_id = str(uuid.uuid4())
    session_state = {"counter": 5, "name": "test"}
    await async_test_agent.arun("Hello", session_id=session_id, session_state=session_state)

    state = await async_test_agent.aget_session_state(session_id=session_id)
    assert state == {"counter": 5, "name": "test"}


def test_update_session_state(test_agent):
    """Test update_session_state merges updates."""
    session_id = str(uuid.uuid4())
    initial_state = {"counter": 0, "items": []}
    test_agent.run("Hello", session_id=session_id, session_state=initial_state)

    result = test_agent.update_session_state({"counter": 5, "new_key": "value"}, session_id=session_id)
    assert result == {"counter": 5, "new_key": "value", "items": []}

    updated_state = test_agent.get_session_state(session_id=session_id)
    assert updated_state["counter"] == 5
    assert updated_state["new_key"] == "value"
    assert "items" in updated_state  # Original key should still exist


@pytest.mark.asyncio
async def test_aupdate_session_state(async_test_agent):
    """Test aupdate_session_state merges updates."""
    session_id = str(uuid.uuid4())
    initial_state = {"counter": 0, "items": []}
    await async_test_agent.arun("Hello", session_id=session_id, session_state=initial_state)

    result = await async_test_agent.aupdate_session_state({"counter": 10}, session_id=session_id)
    assert result == {"counter": 10, "items": []}

    updated_state = await async_test_agent.aget_session_state(session_id=session_id)
    assert updated_state["counter"] == 10


# Tests for get_session_metrics() and aget_session_metrics()
def test_get_session_metrics(test_agent):
    """Test get_session_metrics returns metrics."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)

    metrics = test_agent.get_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0
    assert metrics.input_tokens > 0
    assert metrics.output_tokens > 0


def test_get_session_metrics_multiple_runs(test_agent):
    """Test get_session_metrics accumulates across runs."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)
    test_agent.run("How are you?", session_id=session_id)

    metrics = test_agent.get_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


@pytest.mark.asyncio
async def test_aget_session_metrics(async_test_agent):
    """Test aget_session_metrics returns metrics."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)

    metrics = await async_test_agent.aget_session_metrics(session_id=session_id)
    assert metrics is not None
    assert metrics.total_tokens > 0


# Tests for get_run_output(), aget_run_output(), get_last_run_output(), aget_last_run_output()
def test_get_run_output(test_agent):
    """Test get_run_output returns specific run."""
    session_id = str(uuid.uuid4())
    response = test_agent.run("Hello", session_id=session_id)
    run_id = response.run_id

    retrieved_output = test_agent.get_run_output(run_id=run_id, session_id=session_id)
    assert retrieved_output is not None
    assert retrieved_output.run_id == run_id
    assert retrieved_output.content == response.content


@pytest.mark.asyncio
async def test_aget_run_output(async_test_agent):
    """Test aget_run_output returns specific run."""
    session_id = str(uuid.uuid4())
    response = await async_test_agent.arun("Hello", session_id=session_id)
    run_id = response.run_id

    retrieved_output = await async_test_agent.aget_run_output(run_id=run_id, session_id=session_id)
    assert retrieved_output is not None
    assert retrieved_output.run_id == run_id


def test_get_last_run_output(test_agent):
    """Test get_last_run_output returns the most recent run."""
    session_id = str(uuid.uuid4())
    test_agent.run("First message", session_id=session_id)
    response2 = test_agent.run("Second message", session_id=session_id)

    last_output = test_agent.get_last_run_output(session_id=session_id)
    assert last_output is not None
    assert last_output.run_id == response2.run_id


def test_get_last_run_output_with_default_session_id(test_agent):
    """Test get_last_run_output uses agent's session_id."""
    test_agent.session_id = str(uuid.uuid4())
    response = test_agent.run("Hello")

    last_output = test_agent.get_last_run_output()
    assert last_output is not None
    assert last_output.run_id == response.run_id


@pytest.mark.asyncio
async def test_aget_last_run_output(async_test_agent):
    """Test aget_last_run_output returns the most recent run."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("First message", session_id=session_id)
    response2 = await async_test_agent.arun("Second message", session_id=session_id)

    last_output = await async_test_agent.aget_last_run_output(session_id=session_id)
    assert last_output is not None
    assert last_output.run_id == response2.run_id


# Tests for delete_session() and adelete_session()
def test_delete_session(test_agent):
    """Test delete_session removes a session."""
    session_id = str(uuid.uuid4())
    test_agent.run("Hello", session_id=session_id)

    # Verify session exists
    session = test_agent.get_session(session_id=session_id)
    assert session is not None

    # Delete session
    test_agent.delete_session(session_id=session_id)

    # Verify session is deleted
    session = test_agent.get_session(session_id=session_id)
    assert session is None


@pytest.mark.asyncio
async def test_adelete_session(async_test_agent):
    """Test adelete_session removes a session."""
    session_id = str(uuid.uuid4())
    await async_test_agent.arun("Hello", session_id=session_id)

    # Verify session exists
    session = await async_test_agent.aget_session(session_id=session_id)
    assert session is not None

    # Delete session
    await async_test_agent.adelete_session(session_id=session_id)

    # Verify session is deleted
    session = await async_test_agent.aget_session(session_id=session_id)
    assert session is None


# Test error handling and edge cases
def test_convenience_functions_without_db():
    """Test convenience functions fail gracefully without a database."""
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))

    with pytest.raises(Exception):
        agent.get_chat_history(session_id="test")
    with pytest.raises(Exception):
        agent.get_session_name(session_id="test")
    with pytest.raises(Exception):
        agent.get_session_state(session_id="test")


def test_get_session_state_with_tool_updates(test_agent):
    """Test session state updates via tools."""

    def add_item(run_context: RunContext, item: str) -> str:
        """Add an item to the list."""
        if not run_context.session_state:
            run_context.session_state = {}

        run_context.session_state["items"].append(item)
        return f"Added {item}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=test_agent.db,
        tools=[add_item],
        session_state={"items": []},
    )

    session_id = str(uuid.uuid4())
    agent.run("Add apple to the list", session_id=session_id)

    state = agent.get_session_state(session_id=session_id)
    assert "apple" in state["items"]


def test_multiple_sessions_isolation(test_agent):
    """Test that multiple sessions are properly isolated."""
    session_1 = str(uuid.uuid4())
    session_2 = str(uuid.uuid4())

    # Create two separate sessions
    test_agent.run("Hello from session 1", session_id=session_1, session_state={"id": 1})
    test_agent.run("Hello from session 2", session_id=session_2, session_state={"id": 2})

    # Verify they are independent
    state_1 = test_agent.get_session_state(session_id=session_1)
    state_2 = test_agent.get_session_state(session_id=session_2)

    assert state_1["id"] == 1
    assert state_2["id"] == 2

    history_1 = test_agent.get_chat_history(session_id=session_1)
    history_2 = test_agent.get_chat_history(session_id=session_2)

    # Check that histories are different
    assert any("session 1" in msg.content for msg in history_1)
    assert any("session 2" in msg.content for msg in history_2)
