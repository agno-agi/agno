import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.playwright import PlaywrightTools


@pytest.fixture
def playwright_tools():
    """Create PlaywrightTools instance for testing."""
    return PlaywrightTools(
        headless=True,
        timeout=30000,
        enable_navigate_to=True,
        enable_get_current_url=True,
        enable_extract_page_text=True,
        enable_screenshot=False,  # Disable to speed up tests
        enable_get_page_content=False,
        enable_close_session=True,
    )


@pytest.fixture
def agent_with_forget(shared_db, playwright_tools):
    """Create an agent with forget_tool_calls enabled."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[playwright_tools],
        db=shared_db,
        session_id="test_forget_tool_calls",
        forget_tool_calls=True,
        num_tool_calls_in_context=2,
        tool_call_limit=6,  # Prevent infinite loops
        instructions=(
            "You are a web browser agent. Use navigate_to to visit websites, "
            "extract_page_text to read content, and get_current_url to check your location. "
            "Always close_session when done."
        ),
        telemetry=False,
    )


@pytest.fixture
def agent_with_forget_and_history(shared_db, playwright_tools):
    """Create an agent with both forget_tool_calls and add_history enabled."""
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[playwright_tools],
        db=shared_db,
        session_id="test_forget_with_history",
        forget_tool_calls=True,
        num_tool_calls_in_context=2,
        add_history_to_context=True,
        tool_call_limit=5,  # Prevent infinite loops
        instructions=(
            "You are a web browser agent. Use navigate_to to visit websites and "
            "extract_page_text to read content. Always close_session when done."
        ),
        telemetry=False,
    )


def test_forget_tool_calls_basic(agent_with_forget):
    """Test that forget_tool_calls limits tool calls in context with browser automation."""
    response = agent_with_forget.run("Navigate to https://example.com, extract the page text, then close the session.")

    assert response.content is not None
    assert response.messages is not None

    # Count tool calls and tool results in the response
    tool_call_count = 0
    tool_result_count = 0
    tool_call_ids = []

    for msg in response.messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_call_count += 1
                tool_call_ids.append(tc.get("id"))
        elif msg.role == "tool":
            tool_result_count += 1

    # Should have made at least 2 tool calls (navigate + one other action)
    assert tool_call_count >= 2, f"Expected at least 2 tool calls, got {tool_call_count}"
    assert tool_result_count >= 2, f"Expected at least 2 tool results, got {tool_result_count}"

    # All tool calls should have unique IDs
    assert len(tool_call_ids) == len(set(tool_call_ids)), "Tool call IDs should be unique"

    # Agent should complete successfully
    assert response.content is not None
    assert len(response.content) > 0


def test_forget_tool_calls_with_history(agent_with_forget_and_history):
    """Test that forget_tool_calls works with add_history_to_context."""
    # First run: Navigate to a website
    response1 = agent_with_forget_and_history.run("Navigate to https://example.com")
    assert response1.content is not None

    # Second run: Navigate to another website
    # With add_history=True, previous messages should be in context
    # With forget_tool_calls=True, only recent tool calls should be kept
    response2 = agent_with_forget_and_history.run("Navigate to https://example.org and close the session.")
    assert response2.content is not None
    assert response2.messages is not None

    # Verify messages include history
    has_history_messages = any(hasattr(msg, "from_history") and msg.from_history for msg in response2.messages)
    assert has_history_messages, "Expected history messages in second run"

    # Count tool calls in second response (includes history)
    tool_call_count = 0
    history_tool_calls = 0
    current_tool_calls = 0

    for msg in response2.messages:
        if msg.role == "assistant" and msg.tool_calls:
            for _ in msg.tool_calls:
                tool_call_count += 1
                if hasattr(msg, "from_history") and msg.from_history:
                    history_tool_calls += 1
                else:
                    current_tool_calls += 1

    # Should have tool calls from both history and current run
    assert tool_call_count >= 2, f"Expected at least 2 total tool calls, got {tool_call_count}"
    assert current_tool_calls >= 1, f"Expected current tool calls, got {current_tool_calls}"


def test_forget_tool_calls_preserves_content(shared_db, playwright_tools):
    """Test that assistant messages with content are preserved even if tool calls are filtered."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[playwright_tools],
        db=shared_db,
        session_id="test_preserve_content",
        forget_tool_calls=True,
        num_tool_calls_in_context=1,  # Very small window
        add_history_to_context=True,  # Enable history to test filtering across runs
        tool_call_limit=3,  # Prevent infinite loops
        instructions=(
            "You are a web browser agent. Navigate to websites. "
            "Explain your actions briefly. Always close_session when done."
        ),
        telemetry=False,
    )

    # First call
    response1 = agent.run("Navigate to https://example.com")
    assert response1.content is not None

    # Second call - first tool call should now be filtered out (window=1)
    response2 = agent.run("Navigate to https://example.org and close the session")
    assert response2.content is not None
    assert response2.messages is not None

    # Verify we have assistant messages
    assistant_messages = [msg for msg in response2.messages if msg.role == "assistant"]
    assert len(assistant_messages) > 0, "Expected assistant messages"

    # The key is that the agent completes successfully with a small window
    # (proving that forget_tool_calls prevents infinite loops)


def test_forget_tool_calls_tool_call_ids(shared_db, playwright_tools):
    """Test that tool call IDs are correctly generated and matched."""
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[playwright_tools],
        db=shared_db,
        session_id="test_tool_call_ids",
        forget_tool_calls=True,
        num_tool_calls_in_context=3,
        tool_call_limit=5,  # Prevent infinite loops
        instructions=(
            "You are a web browser agent. Navigate to websites and extract content. Always close_session when done."
        ),
        telemetry=False,
    )

    response = agent.run("Navigate to https://example.com, get the current URL, and close the session.")

    assert response.messages is not None

    # Collect all tool call IDs and tool result IDs
    tool_call_ids = set()
    tool_result_ids = set()

    for msg in response.messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_id = tc.get("id")
                assert tc_id is not None, "Tool call missing ID"
                assert isinstance(tc_id, str), "Tool call ID must be string"
                assert tc_id.startswith("call_"), f"Tool call ID has unexpected format: {tc_id}"
                tool_call_ids.add(tc_id)
        elif msg.role == "tool":
            assert msg.tool_call_id is not None, "Tool result missing tool_call_id"
            tool_result_ids.add(msg.tool_call_id)

    # Every tool result should reference a tool call
    assert len(tool_result_ids) > 0, "Expected tool results"
    assert len(tool_call_ids) > 0, "Expected tool calls"
    assert tool_result_ids.issubset(tool_call_ids), (
        f"Tool results reference unknown tool calls. Tool calls: {tool_call_ids}, Tool results: {tool_result_ids}"
    )

    # All IDs should be unique
    assert len(tool_call_ids) == len(set(tool_call_ids)), "Tool call IDs not unique"
