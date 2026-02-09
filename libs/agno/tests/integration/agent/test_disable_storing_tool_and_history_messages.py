"""
Comprehensive test suite for store_tool_messages and store_history_messages options.

Tests cover:
- Tool result storage (enabled/disabled)
- History message storage (enabled/disabled)
- Combined options
- Edge cases
- Sync and async operations
"""

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.shell import ShellTools


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Create a temporary directory for test databases."""
    return tmp_path_factory.mktemp("test_agent_storage")


# --- Tool Result Storage Tests ---
def test_store_tool_results_enabled_by_default(tmp_path):
    """Test that tool results are stored by default."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
    )

    # Default should be True
    assert agent.store_tool_messages is True

    # Run agent
    response = agent.run("Run command: echo 'test'")

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    assert stored_run.messages is not None
    if stored_run.messages:
        # May or may not have tool calls depending on model behavior
        # But if tools were used, should be stored
        if response.tools:
            assert len(stored_run.tools) > 0


def test_store_tool_results_disabled(tmp_path):
    """Test that tool results are not stored when disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        store_tool_messages=False,
    )

    assert agent.store_tool_messages is False

    # Run agent
    agent.run("Run command: echo 'test'")

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    # Should have NO tool messages
    assert stored_run.messages is not None
    if stored_run.messages:
        tool_messages = [m for m in stored_run.messages if m.role == "tool"]
        assert len(tool_messages) == 0

        # Should have NO tool calls in messages
        for msg in stored_run.messages:
            assert msg.tool_calls is None
            assert msg.tool_call_id is None


def test_tool_results_available_during_execution(tmp_path):
    """Test that tool results are available during execution even when storage is disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        store_tool_messages=False,
    )

    # Run agent
    response = agent.run("Run command: echo 'test'")

    # During execution, tools should be available in the response
    # (They just won't be stored in the database)
    # The response object returned has the data before scrubbing
    assert response is not None


@pytest.mark.asyncio
async def test_store_tool_results_disabled_async(tmp_path):
    """Test that tool results are not stored in async mode."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        store_tool_messages=False,
    )

    # Run agent async
    await agent.arun("Run command: echo 'test'")

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    # Should have NO tool messages
    assert stored_run.messages is not None
    if stored_run.messages:
        tool_messages = [m for m in stored_run.messages if m.role == "tool"]
        assert len(tool_messages) == 0


# --- History Message Storage Tests ---
def test_store_history_messages_disabled_by_default(tmp_path):
    """Test that history messages are NOT stored by default (prevents quadratic storage growth)."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        num_history_runs=2,
    )

    # Default should be False to prevent quadratic storage growth
    assert agent.store_history_messages is False

    # First run to establish history
    agent.run("My name is Alice")

    # Second run with history
    agent.run("What is my name?")

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    assert stored_run.messages is not None
    if stored_run.messages:
        # Should NOT have history messages stored (they're reconstructed on-the-fly)
        history_msgs = [m for m in stored_run.messages if m.from_history]
        assert len(history_msgs) == 0


def test_store_history_messages_disabled(tmp_path):
    """Test that history messages are not stored when disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        num_history_runs=2,
        store_history_messages=False,
    )

    assert agent.store_history_messages is False

    # First run to establish history
    agent.run("My name is Bob")

    # Second run with history
    agent.run("What is my name?")

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    # Should have NO history messages
    assert stored_run.messages is not None
    if stored_run.messages:
        history_msgs = [m for m in stored_run.messages if m.from_history]
        assert len(history_msgs) == 0


def test_history_available_during_execution(tmp_path):
    """Test that history is used during execution even when storage is disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        num_history_runs=2,
        store_history_messages=False,
    )

    # First run
    agent.run("My name is Charlie")

    # Second run - agent should know the name during execution
    response = agent.run("What is my name?")

    # Agent should respond correctly (history was used during execution)
    assert response.content is not None
    # The response should mention the name even though history isn't stored


@pytest.mark.asyncio
async def test_store_history_messages_disabled_async(tmp_path):
    """Test that history messages are not stored in async mode."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        num_history_runs=2,
        store_history_messages=False,
    )

    # First run
    await agent.arun("My name is David")

    # Second run with history
    await agent.arun("What is my name?")

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    # Should have NO history messages
    assert stored_run.messages is not None
    if stored_run.messages:
        history_msgs = [m for m in stored_run.messages if m.from_history]
        assert len(history_msgs) == 0


# --- Combined Options Tests ---
def test_all_storage_disabled(tmp_path):
    """Test with all storage options disabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        store_media=False,
        store_tool_messages=False,
        store_history_messages=False,
    )

    # First run
    agent.run("Tell me about Python")

    # Second run with history and tools
    agent.run("What did we talk about? Run: echo 'test'")

    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    # Check that nothing extra is stored
    assert stored_run.messages is not None
    if stored_run.messages:
        history_msgs = [m for m in stored_run.messages if m.from_history]
        tool_msgs = [m for m in stored_run.messages if m.role == "tool"]
        assert len(history_msgs) == 0
        assert len(tool_msgs) == 0

    assert stored_run.images is None or len(stored_run.images) == 0


def test_selective_storage(tmp_path):
    """Test with selective storage enabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        store_media=True,  # Store media
        store_tool_messages=False,  # Don't store tools
        store_history_messages=True,  # Store history
    )

    # First run
    agent.run("Hello")

    # Second run
    agent.run("Run: echo 'test'")

    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    assert stored_run.messages is not None
    if stored_run.messages:
        # Should have history
        history_msgs = [m for m in stored_run.messages if m.from_history]
        # Should NOT have tool messages
        tool_msgs = [m for m in stored_run.messages if m.role == "tool"]

        assert len(history_msgs) > 0  # History stored
        assert len(tool_msgs) == 0  # Tools not stored


# --- Edge Cases Tests ---
def test_no_tools_used(tmp_path):
    """Test behavior when no tools are actually called."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        store_tool_messages=False,
    )

    # Run without triggering tools
    agent.run("What is 2+2?")

    stored_run = agent.get_last_run_output()
    assert stored_run is not None
    # Should work fine even if no tools were used


def test_no_history_available(tmp_path):
    """Test behavior on first run when no history exists."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        store_history_messages=False,
    )

    # First run (no history to scrub)
    agent.run("Hello")

    stored_run = agent.get_last_run_output()
    assert stored_run is not None
    # Should work fine even with no history


def test_empty_messages_list(tmp_path):
    """Test behavior with empty messages."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        store_tool_messages=False,
        store_history_messages=False,
    )

    # This should handle gracefully even if messages are somehow empty
    agent.run("Test")

    stored_run = agent.get_last_run_output()
    assert stored_run is not None


def test_multiple_runs_same_agent(tmp_path):
    """Test multiple runs with the same agent instance."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        store_tool_messages=False,
        store_history_messages=False,
    )

    # Multiple runs
    for i in range(3):
        agent.run(f"Run {i}: echo 'test{i}'")

        stored_run = agent.get_last_run_output()
        assert stored_run is not None

        # Each run should have no tool/history messages stored
        assert stored_run.messages is not None
        if stored_run.messages:
            history_msgs = [m for m in stored_run.messages if m.from_history]
            tool_msgs = [m for m in stored_run.messages if m.role == "tool"]
            assert len(history_msgs) == 0
            assert len(tool_msgs) == 0


# --- Streaming Mode Tests ---
def test_store_tool_results_disabled_streaming(tmp_path):
    """Test tool result storage with streaming enabled."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ShellTools()],
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        store_tool_messages=False,
        stream=True,
    )

    # Run with streaming
    response_iterator = agent.run("Run: echo 'test'")

    # Consume the stream
    for event in response_iterator:
        pass

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    assert stored_run.messages is not None
    if stored_run.messages:
        tool_msgs = [m for m in stored_run.messages if m.role == "tool"]
        assert len(tool_msgs) == 0


@pytest.mark.asyncio
async def test_store_history_messages_disabled_streaming_async(tmp_path):
    """Test history message storage with async streaming."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        add_history_to_context=True,
        store_history_messages=False,
        stream=True,
    )

    # First run
    async for event in agent.arun("My name is Eve"):
        pass

    # Second run with streaming
    async for event in agent.arun("What is my name?"):
        pass

    # Check stored run
    stored_run = agent.get_last_run_output()
    assert stored_run is not None

    assert stored_run.messages is not None
    if stored_run.messages:
        history_msgs = [m for m in stored_run.messages if m.from_history]
        assert len(history_msgs) == 0
