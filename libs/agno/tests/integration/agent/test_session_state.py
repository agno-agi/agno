import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.models.openai.chat import OpenAIChat


def add_item(session_state: Dict[str, Any], item: str) -> str:
    """Add an item to the shopping list (sync version)."""
    session_state["shopping_list"].append(item)
    return f"The shopping list is now {session_state['shopping_list']}"


async def async_add_item(session_state: Dict[str, Any], item: str) -> str:
    """Add an item to the shopping list (async version)."""
    session_state["shopping_list"].append(item)
    return f"The shopping list is now {session_state['shopping_list']}"


def test_session_state_precedence_all_three_layers(shared_db):
    """Test precedence when all three session state layers are present.

    Expected precedence: session_state_from_run > session_state_from_db > self.session_state
    """
    session_id = f"precedence_test_{uuid.uuid4()}"

    # Layer 1: Agent default session_state (lowest priority)
    agent_default_state = {"name": "agent_default", "shared_key": "from_agent_default", "agent_only": "agent_value"}

    # Create agent with default state
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"), db=shared_db, session_state=agent_default_state, session_id=session_id
    )

    # First run to establish DB state
    db_state = {"name": "db_saved", "shared_key": "from_db", "db_only": "db_value"}
    agent.run("First run", session_state=db_state)

    # Verify DB state was saved
    session_from_db = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    assert session_from_db.session_data["session_state"]["name"] == "db_saved"

    # Layer 3: Run-level session_state (highest priority)
    run_state = {"name": "run_override", "shared_key": "from_run", "run_only": "run_value"}

    # Second run with run-level state should override DB state for conflicting keys
    agent.run("Second run", session_state=run_state)

    # Verify final precedence
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    # Run state should take precedence
    assert final_state["name"] == "run_override"
    assert final_state["shared_key"] == "from_run"
    assert final_state["run_only"] == "run_value"

    # DB-only keys should remain
    assert final_state["db_only"] == "db_value"

    # Agent-only keys should remain
    assert final_state["agent_only"] == "agent_value"


def test_session_state_precedence_db_and_run_only(shared_db):
    """Test precedence when only DB and run state are present (no agent default)."""
    session_id = f"db_run_test_{uuid.uuid4()}"

    # Create agent with no default session_state
    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db, session_id=session_id)

    # First run establishes DB state
    db_state = {"db_key": "db_value", "shared": "from_db"}
    agent.run("First run", session_state=db_state)

    # Second run with conflicting run state
    run_state = {"run_key": "run_value", "shared": "from_run"}
    agent.run("Second run", session_state=run_state)

    # Verify run state takes precedence
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    assert final_state["shared"] == "from_run"  # Run overrides DB
    assert final_state["run_key"] == "run_value"  # Run key present
    assert final_state["db_key"] == "db_value"  # DB key preserved


def test_session_state_precedence_agent_and_run_only(shared_db):
    """Test precedence when only agent default and run state are present (no DB state)."""
    session_id = f"agent_run_test_{uuid.uuid4()}"

    agent_state = {"agent_key": "agent_value", "shared": "from_agent"}

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db, session_state=agent_state, session_id=session_id)

    # Single run with run state
    run_state = {"run_key": "run_value", "shared": "from_run"}
    agent.run("Single run", session_state=run_state)

    # Verify run state takes precedence over agent default
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    assert final_state["shared"] == "from_run"  # Run overrides agent
    assert final_state["run_key"] == "run_value"  # Run key present
    assert final_state["agent_key"] == "agent_value"  # Agent key preserved

    assert agent.session_state == agent_state  # Agent default should not be modified
    assert agent.get_session_state() == final_state


def test_session_state_precedence_empty_run_state_preserves_db(shared_db):
    """Test that empty/None run state preserves DB state correctly."""
    session_id = f"empty_run_test_{uuid.uuid4()}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={"agent_key": "agent_value"},
        session_id=session_id,
    )

    # First run establishes DB state
    db_state = {"db_key": "db_value", "modified": "original"}
    agent.run("First run", session_state=db_state)

    # Second run with None session_state - should preserve DB
    agent.run("Second run", session_state=None)

    # Verify DB state is preserved
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    assert final_state["db_key"] == "db_value"
    assert final_state["modified"] == "original"
    assert final_state["agent_key"] == "agent_value"  # Agent key still there

    # Third run with empty dict - should also preserve DB
    agent.run("Third run", session_state={})

    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    # Empty dict should not override anything
    assert final_state["db_key"] == "db_value"
    assert final_state["modified"] == "original"
    assert final_state["agent_key"] == "agent_value"


def test_session_state_precedence_default_state_does_not_override_db(shared_db):
    """Test that empty/None run state preserves DB state correctly."""
    session_id = f"empty_run_test_{uuid.uuid4()}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={"agent_key": []},
        session_id=session_id,
    )

    # First run establishes DB state
    db_state = {"agent_key": ["foo", "bar"]}
    agent.run("First run", session_state=db_state)

    # Second run with None session_state - should preserve DB
    agent.run("Second run", session_state=None)

    # Verify DB state is preserved
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    assert final_state["agent_key"] == ["foo", "bar"]  # Agent key still there


def test_session_state_tool_updates_persist_correctly(shared_db):
    """Test that tool updates to session state persist correctly like the working example."""

    # Copy exactly from the working test
    def add_item(session_state: Dict[str, Any], item: str) -> str:
        """Add an item to the shopping list."""
        session_state["shopping_list"].append(item)
        return f"The shopping list is now {session_state['shopping_list']}"

    # Create an Agent that maintains state
    agent = Agent(
        db=shared_db,
        session_state={"shopping_list": []},
        tools=[add_item],
        instructions="Current state (shopping list) is: {shopping_list}",
        markdown=True,
    )

    agent.run("Add oranges to my shopping list")

    response = agent.run(
        'Current shopping list: {shopping_list}. Other random json ```json { "properties": { "title": { "title": "a" } } }```'
    )

    assert (
        response.messages[1].content
        == 'Current shopping list: [\'oranges\']. Other random json ```json { "properties": { "title": { "title": "a" } } }```'
    )


def test_manual_session_state_update(shared_db):
    """Test that manual session state update works correctly."""

    def add_item(session_state: Dict[str, Any], item: str) -> str:
        """Add an item to the shopping list."""
        session_state["shopping_list"].append(item)
        return f"The shopping list is now {session_state['shopping_list']}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={"shopping_list": []},
        add_session_state_to_context=True,
        tools=[add_item],
    )
    agent.run("Add oranges to my shopping list")
    agent.update_session_state({"shopping_list": ["oranges", "bananas"]})

    assert agent.get_session_state()["shopping_list"] == ["oranges", "bananas"]

    response = agent.run("What's on my list?")
    assert "oranges" in response.content.lower()
    assert "bananas" in response.content.lower()


def test_session_state_precedence_with_nested_dicts(shared_db):
    """Test precedence with nested dictionary structures."""
    session_id = f"nested_test_{uuid.uuid4()}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={
            "user_profile": {"name": "default", "age": 25},
            "settings": {"theme": "light", "notifications": True},
        },
        session_id=session_id,
    )

    # First run - establish DB state with nested updates
    db_state = {"user_profile": {"name": "db_user", "email": "db@example.com"}, "settings": {"theme": "dark"}}
    agent.run("First run", session_state=db_state)

    # Second run - run state should override at nested level
    run_state = {"user_profile": {"name": "run_user", "phone": "123-456-7890"}, "new_section": {"new_key": "new_value"}}
    agent.run("Second run", session_state=run_state)

    # Verify nested precedence
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    # Run state should override nested structures
    assert final_state["user_profile"]["name"] == "run_user"  # Run overrides
    assert final_state["user_profile"]["phone"] == "123-456-7890"  # Run adds
    assert final_state["user_profile"]["email"] == "db@example.com"  # DB preserved
    assert final_state["user_profile"]["age"] == 25  # Agent default preserved

    # Settings should be preserved from DB/agent
    assert final_state["settings"]["theme"] == "dark"  # DB value
    assert final_state["settings"]["notifications"] is True  # Agent default

    # New section from run
    assert final_state["new_section"]["new_key"] == "new_value"


@pytest.mark.asyncio
async def test_session_state_precedence_async(shared_db):
    """Test session state precedence works correctly in async mode."""
    session_id = f"async_test_{uuid.uuid4()}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={"async_test": "agent_default"},
        session_id=session_id,
    )

    # Async first run
    await agent.arun("First run", session_state={"async_test": "db_state", "db_key": "db_value"})

    # Async second run with run state
    await agent.arun("Second run", session_state={"async_test": "run_state", "run_key": "run_value"})

    # Verify precedence same as sync
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    assert final_state["async_test"] == "run_state"  # Run overrides
    assert final_state["run_key"] == "run_value"  # Run key
    assert final_state["db_key"] == "db_value"  # DB key preserved


def test_session_state_precedence_streaming(shared_db):
    """Test session state precedence works correctly in streaming mode."""
    session_id = f"stream_test_{uuid.uuid4()}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={"stream_test": "agent_default"},
        session_id=session_id,
    )

    # Streaming first run
    for _ in agent.run("First run", session_state={"stream_test": "db_state", "db_key": "db_value"}, stream=True):
        pass

    # Streaming second run with run state
    for _ in agent.run("Second run", session_state={"stream_test": "run_state", "run_key": "run_value"}, stream=True):
        pass

    # Verify precedence same as non-streaming
    final_session = shared_db.get_session(session_id=session_id, session_type=SessionType.AGENT)
    final_state = final_session.session_data["session_state"]

    assert final_state["stream_test"] == "run_state"  # Run overrides
    assert final_state["run_key"] == "run_value"  # Run key
    assert final_state["db_key"] == "db_value"  # DB key preserved


def test_session_state_overwriting(shared_db):
    """Test the stored session_state can be overwritten by the run state."""
    session_id = f"overwrite_test_{uuid.uuid4()}"

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        session_state={"overwrite_test": "agent_default"},
        session_id=session_id,
        # Overwritting should work
        overwrite_db_session_state=True,
    )

    agent.run("First run", session_state={"original_field": "original_value"})
    assert agent.get_session_state()["original_field"] == "original_value"

    agent.run("Second run", session_state={"new_field": "new_value"})

    # Asserting the original session_state was overwritten
    assert agent.get_session_state().get("original_field") is None
    assert agent.get_session_state().get("new_field") == "new_value"


# ==============================================================================
# Section 3: RunOutput & RunCompletedEvent Tests
# ==============================================================================


def test_session_state_in_run_output(shared_db):
    """Test that RunOutput contains the updated session_state in non-streaming mode."""
    session_id = str(uuid.uuid4())
    model = OpenAIChat(id="gpt-4o-mini")
    agent = Agent(
        model=model,
        db=shared_db,
        session_id=session_id,
        session_state={"shopping_list": []},
        tools=[add_item],
        markdown=True,
    )

    # Mock the OpenAI API response to simulate LLM calling the add_item tool
    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [
        MagicMock(
            id="call_123",
            type="function",
            function=MagicMock(name="add_item", arguments='{"item": "apples"}'),
        )
    ]
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "tool_calls"

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = MagicMock(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    mock_completion.model = "gpt-4o-mini"
    mock_completion.id = "chatcmpl-123"

    # Mock the second response after tool execution (final response)
    mock_choice_final = MagicMock()
    mock_choice_final.message.content = "I've added apples to your shopping list."
    mock_choice_final.message.tool_calls = None
    mock_choice_final.message.role = "assistant"
    mock_choice_final.finish_reason = "stop"

    mock_completion_final = MagicMock()
    mock_completion_final.choices = [mock_choice_final]
    mock_completion_final.usage = MagicMock(prompt_tokens=60, completion_tokens=10, total_tokens=70)
    mock_completion_final.model = "gpt-4o-mini"
    mock_completion_final.id = "123"

    # Patch the OpenAI client's create method to return our mocks
    client = model.get_client()
    with patch.object(client.chat.completions, "create", side_effect=[mock_completion, mock_completion_final]):
        # Execute the run - this will use the real agent.run logic
        # but with mocked LLM API responses
        response = agent.run("Add apples to my shopping list")

    # Verify RunOutput has session_state field
    assert response.session_state is not None, "RunOutput should have session_state"
    assert isinstance(response.session_state, dict), "session_state should be a dict"
    assert "shopping_list" in response.session_state, "shopping_list key should be present"
    assert isinstance(response.session_state["shopping_list"], list), "shopping_list should be a list"

    # Verify state was updated by the tool
    assert len(response.session_state.get("shopping_list", [])) == 1, "Shopping list should have 1 item"
    assert "apples" in response.session_state["shopping_list"], "Shopping list should contain apples"


def test_session_state_in_run_completed_event_stream(shared_db):
    """Test that RunCompletedEvent contains session_state in streaming mode."""
    session_id = str(uuid.uuid4())
    model = OpenAIChat(id="gpt-4o-mini")
    agent = Agent(
        model=model,
        db=shared_db,
        session_id=session_id,
        session_state={"shopping_list": ["bananas"]},
        tools=[add_item],
        markdown=True,
    )

    # Mock the OpenAI API response to simulate LLM calling the add_item tool
    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [
        MagicMock(
            id="call_123",
            type="function",
            function=MagicMock(name="add_item", arguments='{"item": "oranges"}'),
        )
    ]
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "tool_calls"

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = MagicMock(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    mock_completion.model = "gpt-4o-mini"
    mock_completion.id = "chatcmpl-123"

    # Mock the second response after tool execution (final response)
    mock_choice_final = MagicMock()
    mock_choice_final.message.content = "I've added oranges to your shopping list."
    mock_choice_final.message.tool_calls = None
    mock_choice_final.message.role = "assistant"
    mock_choice_final.finish_reason = "stop"

    mock_completion_final = MagicMock()
    mock_completion_final.choices = [mock_choice_final]
    mock_completion_final.usage = MagicMock(prompt_tokens=60, completion_tokens=10, total_tokens=70)
    mock_completion_final.model = "gpt-4o-mini"
    mock_completion_final.id = "123"

    run_completed_event = None

    # Patch the OpenAI client's create method to return our mocks
    client = model.get_client()
    with patch.object(client.chat.completions, "create", side_effect=[mock_completion, mock_completion_final]):
        for event in agent.run("Add oranges to my shopping list", stream=True, stream_intermediate_steps=True):
            if hasattr(event, "event") and event.event == "RunCompleted":
                run_completed_event = event
                break

    # Verify RunCompletedEvent structure
    assert run_completed_event is not None, "Should receive RunCompleted event"
    assert run_completed_event.session_state is not None, "RunCompletedEvent should have session_state"
    assert isinstance(run_completed_event.session_state, dict), "session_state should be a dict"
    assert "shopping_list" in run_completed_event.session_state, "shopping_list key should be present"
    assert "bananas" in run_completed_event.session_state.get("shopping_list", []), "Initial item should be preserved"

    # Verify state was updated by the tool
    assert len(run_completed_event.session_state.get("shopping_list", [])) == 2, "Shopping list should have 2 items"
    assert "oranges" in run_completed_event.session_state["shopping_list"], "Shopping list should contain oranges"


@pytest.mark.asyncio
async def test_session_state_in_run_output_async(shared_db):
    """Test that RunOutput contains session_state in async non-streaming mode."""
    session_id = str(uuid.uuid4())
    model = OpenAIChat(id="gpt-4o-mini")
    agent = Agent(
        model=model,
        db=shared_db,
        session_id=session_id,
        session_state={"shopping_list": []},
        tools=[async_add_item],
        markdown=True,
    )

    # Mock the OpenAI API response to simulate LLM calling the add_item tool
    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [
        MagicMock(
            id="call_123",
            type="function",
            function=MagicMock(name="add_item", arguments='{"item": "apples"}'),
        )
    ]
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "tool_calls"

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = MagicMock(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    mock_completion.model = "gpt-4o-mini"
    mock_completion.id = "chatcmpl-123"

    # Mock the second response after tool execution (final response)
    mock_choice_final = MagicMock()
    mock_choice_final.message.content = "I've added apples to your shopping list."
    mock_choice_final.message.tool_calls = None
    mock_choice_final.message.role = "assistant"
    mock_choice_final.finish_reason = "stop"

    mock_completion_final = MagicMock()
    mock_completion_final.choices = [mock_choice_final]
    mock_completion_final.usage = MagicMock(prompt_tokens=60, completion_tokens=10, total_tokens=70)
    mock_completion_final.model = "gpt-4o-mini"
    mock_completion_final.id = "123"

    # Patch the OpenAI client's create method to return our mocks
    client = model.get_client()
    with patch.object(client.chat.completions, "create", side_effect=[mock_completion, mock_completion_final]):
        response = await agent.arun("Add apples to my shopping list")

    # Verify RunOutput has session_state
    assert response.session_state is not None, "RunOutput should have session_state"
    assert isinstance(response.session_state, dict), "session_state should be a dict"
    assert "shopping_list" in response.session_state, "shopping_list key should be present"
    assert isinstance(response.session_state["shopping_list"], list), "shopping_list should be a list"

    # Verify state was updated by the tool
    assert len(response.session_state.get("shopping_list", [])) == 1, "Shopping list should have 1 item"
    assert "apples" in response.session_state["shopping_list"], "Shopping list should contain apples"


@pytest.mark.asyncio
async def test_session_state_in_run_completed_event_stream_async(shared_db):
    """Test that RunCompletedEvent contains session_state in async streaming mode."""
    session_id = str(uuid.uuid4())
    model = OpenAIChat(id="gpt-4o-mini")
    agent = Agent(
        model=model,
        db=shared_db,
        session_id=session_id,
        session_state={"shopping_list": ["bananas"]},
        tools=[async_add_item],
        markdown=True,
    )

    # Mock the OpenAI API response to simulate LLM calling the add_item tool
    mock_choice = MagicMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [
        MagicMock(
            id="call_123",
            type="function",
            function=MagicMock(name="add_item", arguments='{"item": "oranges"}'),
        )
    ]
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "tool_calls"

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = MagicMock(prompt_tokens=50, completion_tokens=20, total_tokens=70)
    mock_completion.model = "gpt-4o-mini"
    mock_completion.id = "chatcmpl-123"

    # Mock the second response after tool execution (final response)
    mock_choice_final = MagicMock()
    mock_choice_final.message.content = "I've added oranges to your shopping list."
    mock_choice_final.message.tool_calls = None
    mock_choice_final.message.role = "assistant"
    mock_choice_final.finish_reason = "stop"

    mock_completion_final = MagicMock()
    mock_completion_final.choices = [mock_choice_final]
    mock_completion_final.usage = MagicMock(prompt_tokens=60, completion_tokens=10, total_tokens=70)
    mock_completion_final.model = "gpt-4o-mini"
    mock_completion_final.id = "123"

    run_completed_event = None

    # Patch the OpenAI client's create method to return our mocks
    client = model.get_client()
    with patch.object(client.chat.completions, "create", side_effect=[mock_completion, mock_completion_final]):
        async for event in agent.arun("Add oranges to my shopping list", stream=True, stream_intermediate_steps=True):
            if hasattr(event, "event") and event.event == "RunCompleted":
                run_completed_event = event
                break

    # Verify RunCompletedEvent structure
    assert run_completed_event is not None, "Should receive RunCompleted event"
    assert run_completed_event.session_state is not None, "RunCompletedEvent should have session_state"
    assert isinstance(run_completed_event.session_state, dict), "session_state should be a dict"
    assert "shopping_list" in run_completed_event.session_state, "shopping_list key should be present"
    assert "bananas" in run_completed_event.session_state.get("shopping_list", []), "Initial item should be preserved"

    # Verify state was updated by the tool
    assert len(run_completed_event.session_state.get("shopping_list", [])) == 2, "Shopping list should have 2 items"
    assert "oranges" in run_completed_event.session_state["shopping_list"], "Shopping list should contain oranges"
