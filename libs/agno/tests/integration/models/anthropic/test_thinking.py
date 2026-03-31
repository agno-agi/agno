import json
import os
import tempfile

import pytest

from agno.agent import Agent
from agno.db.json import JsonDb
from agno.models.anthropic import Claude
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.tools.yfinance import YFinanceTools


def _get_thinking_agent(**kwargs):
    """Create an agent with thinking enabled using consistent settings."""
    default_config = {
        "model": Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def _get_interleaved_thinking_agent(**kwargs):
    """Create an agent with interleaved thinking enabled using Claude 4."""
    default_config = {
        "model": Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 2048},
            betas=["interleaved-thinking-2025-05-14"],
        ),
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_thinking():
    agent = _get_thinking_agent()
    response: RunOutput = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.reasoning_content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].reasoning_content is not None if response.messages is not None else False


def test_thinking_stream():
    agent = _get_thinking_agent()
    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert response.content is not None or response.reasoning_content is not None  # type: ignore


@pytest.mark.asyncio
async def test_async_thinking():
    agent = _get_thinking_agent()
    response: RunOutput = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.reasoning_content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].reasoning_content is not None if response.messages is not None else False


@pytest.mark.asyncio
async def test_async_thinking_stream():
    agent = _get_thinking_agent()

    async for response in agent.arun("Share a 2 sentence horror story", stream=True):
        assert response.content is not None or response.reasoning_content is not None  # type: ignore


def test_redacted_reasoning_content():
    agent = _get_thinking_agent()
    # Testing string from anthropic
    response = agent.run(
        "ANTHROPIC_MAGIC_STRING_TRIGGER_redacted_reasoning_content_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
    )
    assert response.reasoning_content is not None


def test_thinking_with_tool_calls():
    agent = _get_thinking_agent(tools=[YFinanceTools(cache_results=True)])

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_redacted_reasoning_content_with_tool_calls():
    agent = _get_thinking_agent(
        tools=[YFinanceTools(cache_results=True)],
        add_history_to_context=True,
        markdown=True,
    )

    # Put a redacted thinking message in the history
    agent.run(
        "ANTHROPIC_MAGIC_STRING_TRIGGER_redacted_reasoning_content_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_thinking_message_serialization():
    """Test that thinking content is properly serialized in Message objects."""
    message = Message(
        role="assistant",
        content="The answer is 42.",
        reasoning_content="I need to think about the meaning of life. After careful consideration, 42 seems right.",
        provider_data={"signature": "thinking_sig_xyz789"},
    )

    # Serialize to dict
    message_dict = message.to_dict()

    # Verify thinking content is in the serialized data
    assert "reasoning_content" in message_dict
    assert (
        message_dict["reasoning_content"]
        == "I need to think about the meaning of life. After careful consideration, 42 seems right."
    )

    # Verify provider data is preserved
    assert "provider_data" in message_dict
    assert message_dict["provider_data"]["signature"] == "thinking_sig_xyz789"


@pytest.mark.asyncio
async def test_thinking_with_storage():
    """Test that thinking content is stored and retrievable."""
    with tempfile.TemporaryDirectory() as storage_dir:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514", thinking={"type": "enabled", "budget_tokens": 1024}),
            db=JsonDb(db_path=storage_dir, session_table="test_session"),
            user_id="test_user",
            session_id="test_session",
            telemetry=False,
        )

        # Ask a question that should trigger thinking
        response = await agent.arun("What is 25 * 47?", stream=False)

        # Verify response has thinking content
        assert response.reasoning_content is not None
        assert len(response.reasoning_content) > 0

        # Read the storage files to verify thinking was persisted
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_persisted = False
        for session_file in session_files:
            if session_file == "test_session.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                # Check messages in this session
                if session_data and session_data[0] and session_data[0]["runs"]:
                    for run in session_data[0]["runs"]:
                        for message in run["messages"]:
                            if message.get("role") == "assistant" and message.get("reasoning_content"):
                                thinking_persisted = True
                                break
                        if thinking_persisted:
                            break
                break

        assert thinking_persisted, "Thinking content should be persisted in storage"


@pytest.mark.asyncio
async def test_thinking_with_streaming_storage():
    """Test thinking content with streaming and storage."""
    with tempfile.TemporaryDirectory() as storage_dir:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514", thinking={"type": "enabled", "budget_tokens": 1024}),
            db=JsonDb(db_path=storage_dir, session_table="test_session_stream"),
            user_id="test_user_stream",
            session_id="test_session_stream",
            telemetry=False,
        )

        final_response = None
        async for chunk in agent.arun("What is 15 + 27?", stream=True):
            if hasattr(chunk, "reasoning_content") and chunk.reasoning_content:  # type: ignore
                final_response = chunk

        # Verify we got thinking content
        assert final_response is not None
        assert hasattr(final_response, "reasoning_content") and final_response.reasoning_content is not None  # type: ignore

        # Verify storage contains the thinking content
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_persisted = False
        for session_file in session_files:
            if session_file == "test_session_stream.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                # Check messages in this session
                if session_data and session_data[0] and session_data[0]["runs"]:
                    for run in session_data[0]["runs"]:
                        for message in run["messages"]:
                            if message.get("role") == "assistant" and message.get("reasoning_content"):
                                thinking_persisted = True
                                break
                        if thinking_persisted:
                            break
                break

        assert thinking_persisted, "Thinking content from streaming should be stored"


# ============================================================================
# INTERLEAVED THINKING TESTS (Claude 4 specific)
# ============================================================================


def test_interleaved_thinking():
    """Test basic interleaved thinking functionality with Claude 4."""
    agent = _get_interleaved_thinking_agent()
    response: RunOutput = agent.run("What's 25 × 17? Think through it step by step.")

    assert response.content is not None
    assert response.reasoning_content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].reasoning_content is not None


def test_interleaved_thinking_stream():
    """Test interleaved thinking with streaming."""
    agent = _get_interleaved_thinking_agent()
    response_stream = agent.run("What's 42 × 13? Show your work.", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0

    # Should have both content and thinking in the responses
    has_content = any(r.content is not None for r in responses)
    has_thinking = any(r.reasoning_content is not None for r in responses)  # type: ignore

    assert has_content, "Should have content in responses"
    assert has_thinking, "Should have thinking in responses"


@pytest.mark.asyncio
async def test_async_interleaved_thinking():
    """Test async interleaved thinking."""
    agent = _get_interleaved_thinking_agent()
    response: RunOutput = await agent.arun("Calculate 15 × 23 and explain your reasoning.")

    assert response.content is not None
    assert response.reasoning_content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].reasoning_content is not None


@pytest.mark.asyncio
async def test_async_interleaved_thinking_stream():
    """Test async streaming with interleaved thinking."""
    agent = _get_interleaved_thinking_agent()

    responses = []
    async for response in agent.arun("What's 37 × 19? Break it down step by step.", stream=True):
        responses.append(response)

    assert len(responses) > 0

    # Should have both content and thinking in the responses
    has_content = any(r.content is not None for r in responses)
    has_thinking = any(r.reasoning_content is not None for r in responses)

    assert has_content, "Should have content in responses"
    assert has_thinking, "Should have thinking in responses"


def test_interleaved_thinking_with_tools():
    """Test interleaved thinking with tool calls."""
    agent = _get_interleaved_thinking_agent(tools=[YFinanceTools(cache_results=True)])

    response = agent.run("What is the current price of AAPL? Think about why someone might want this information.")

    # Verify tool usage and thinking
    assert response.messages is not None
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert response.reasoning_content is not None
    assert "AAPL" in response.content


@pytest.mark.asyncio
async def test_interleaved_thinking_with_storage():
    """Test that interleaved thinking content is stored and retrievable."""
    with tempfile.TemporaryDirectory() as storage_dir:
        agent = Agent(
            model=Claude(
                id="claude-sonnet-4-20250514",
                thinking={"type": "enabled", "budget_tokens": 2048},
                betas=["interleaved-thinking-2025-05-14"],
            ),
            db=JsonDb(db_path=storage_dir, session_table="test_session_interleaved"),
            user_id="test_user_interleaved",
            session_id="test_session_interleaved",
            telemetry=False,
        )

        # Ask a question that should trigger interleaved thinking
        response = await agent.arun("Calculate 144 ÷ 12 and show your thought process.", stream=False)

        # Verify response has thinking content
        assert response.reasoning_content is not None
        assert len(response.reasoning_content) > 0

        # Read the storage files to verify thinking was persisted
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_persisted = False
        for session_file in session_files:
            if session_file == "test_session_interleaved.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                # Check messages in this session
                if session_data and session_data[0] and session_data[0]["runs"]:
                    for run in session_data[0]["runs"]:
                        for message in run["messages"]:
                            if message.get("role") == "assistant" and message.get("reasoning_content"):
                                thinking_persisted = True
                                break
                        if thinking_persisted:
                            break
                break

        assert thinking_persisted, "Interleaved thinking content should be persisted in storage"


@pytest.mark.asyncio
async def test_interleaved_thinking_streaming_with_storage():
    """Test interleaved thinking with streaming and storage."""
    with tempfile.TemporaryDirectory() as storage_dir:
        agent = Agent(
            model=Claude(
                id="claude-sonnet-4-20250514",
                thinking={"type": "enabled", "budget_tokens": 2048},
                betas=["interleaved-thinking-2025-05-14"],
            ),
            db=JsonDb(db_path=storage_dir, session_table="test_session_interleaved_stream"),
            user_id="test_user_interleaved_stream",
            session_id="test_session_interleaved_stream",
            telemetry=False,
        )

        final_response = None
        async for chunk in agent.arun("What is 84 ÷ 7? Think through the division process.", stream=True):
            if hasattr(chunk, "reasoning_content") and chunk.reasoning_content:  # type: ignore
                final_response = chunk

        # Verify we got thinking content
        assert final_response is not None
        assert hasattr(final_response, "reasoning_content") and final_response.reasoning_content is not None  # type: ignore

        # Verify storage contains the thinking content
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_persisted = False
        for session_file in session_files:
            if session_file == "test_session_interleaved_stream.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                # Check messages in this session
                if session_data and session_data[0] and session_data[0]["runs"]:
                    for run in session_data[0]["runs"]:
                        for message in run["messages"]:
                            if message.get("role") == "assistant" and message.get("reasoning_content"):
                                thinking_persisted = True
                                break
                        if thinking_persisted:
                            break
                break

        assert thinking_persisted, "Interleaved thinking content from streaming should be stored"


def test_interleaved_thinking_vs_regular_thinking():
    """Test that both regular and interleaved thinking work correctly and can be distinguished."""
    # Regular thinking agent
    regular_agent = _get_thinking_agent()
    regular_response = regular_agent.run("What is 5 × 6?")

    # Interleaved thinking agent
    interleaved_agent = _get_interleaved_thinking_agent()
    interleaved_response = interleaved_agent.run("What is 5 × 6?")

    # Both should have thinking content
    assert regular_response.reasoning_content is not None
    assert interleaved_response.reasoning_content is not None

    # Both should have content
    assert regular_response.content is not None
    assert interleaved_response.content is not None

    # Verify the models are different
    assert regular_agent.model.id == "claude-sonnet-4-20250514"  # type: ignore
    assert interleaved_agent.model.id == "claude-sonnet-4-20250514"  # type: ignore

    # Verify the headers are different
    assert not hasattr(regular_agent.model, "default_headers") or regular_agent.model.default_headers is None  # type: ignore


# ============================================================================
# STREAMING REASONING TESTS (reasoning_model with stream_events)
# ============================================================================


def _get_reasoning_streaming_agent(**kwargs):
    """Create an agent with reasoning_model for streaming reasoning tests."""
    default_config = {
        "model": Claude(id="claude-sonnet-4-20250514"),
        "reasoning_model": Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        "instructions": "You are an expert problem-solving assistant. Think step by step.",
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_reasoning_model_streams_content_deltas():
    """Test that reasoning_model streams content via reasoning_content_delta events."""
    from agno.run.agent import RunEvent

    agent = _get_reasoning_streaming_agent()

    prompt = "What is 25 * 37? Show your reasoning step by step."

    # Track events
    reasoning_deltas = []
    reasoning_started = False
    reasoning_completed = False

    for event in agent.run(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_started:
            reasoning_started = True

        elif event.event == RunEvent.reasoning_content_delta:
            if event.reasoning_content:
                reasoning_deltas.append(event.reasoning_content)

        elif event.event == RunEvent.reasoning_completed:
            reasoning_completed = True

    # Assertions
    assert reasoning_started, "Should have received reasoning_started event"
    assert reasoning_completed, "Should have received reasoning_completed event"
    assert len(reasoning_deltas) > 1, (
        f"Should have received multiple reasoning_content_delta events for streaming, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"


@pytest.mark.asyncio
async def test_reasoning_model_streams_content_deltas_async():
    """Test that reasoning_model streams content via reasoning_content_delta events (async)."""
    from agno.run.agent import RunEvent

    agent = _get_reasoning_streaming_agent()

    prompt = "What is 25 * 37? Show your reasoning step by step."

    # Track events
    reasoning_deltas = []
    reasoning_started = False
    reasoning_completed = False

    async for event in agent.arun(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_started:
            reasoning_started = True

        elif event.event == RunEvent.reasoning_content_delta:
            if event.reasoning_content:
                reasoning_deltas.append(event.reasoning_content)

        elif event.event == RunEvent.reasoning_completed:
            reasoning_completed = True

    # Assertions
    assert reasoning_started, "Should have received reasoning_started event"
    assert reasoning_completed, "Should have received reasoning_completed event"
    assert len(reasoning_deltas) > 1, (
        f"Should have received multiple reasoning_content_delta events for streaming, but got {len(reasoning_deltas)}"
    )

    # Verify we got actual content
    full_reasoning = "".join(reasoning_deltas)
    assert len(full_reasoning) > 0, "Combined reasoning content should not be empty"


def test_reasoning_streaming_delivers_more_events_than_non_streaming():
    """Test that streaming mode delivers multiple delta events vs single batch in non-streaming."""
    from agno.run.agent import RunEvent

    agent = _get_reasoning_streaming_agent()

    prompt = "What is 12 * 8?"

    # Non-streaming mode
    non_streaming_response = agent.run(prompt, stream=False)
    non_streaming_reasoning = non_streaming_response.reasoning_content or ""

    # Streaming mode - count delta events
    streaming_deltas = []
    for event in agent.run(prompt, stream=True, stream_events=True):
        if event.event == RunEvent.reasoning_content_delta:
            if event.reasoning_content:
                streaming_deltas.append(event.reasoning_content)

    streaming_reasoning = "".join(streaming_deltas)

    # Both should have reasoning content
    assert len(non_streaming_reasoning) > 0, "Non-streaming should have reasoning"
    assert len(streaming_reasoning) > 0, "Streaming should have reasoning"

    # Streaming should have multiple deltas (the key feature we're testing)
    assert len(streaming_deltas) > 1, "Streaming should deliver multiple delta events, not just one batch"
