import json
import os
import tempfile

import pytest

from agno.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.anthropic import Claude
from agno.models.message import Message
from agno.run.response import RunResponse
from agno.storage.json import JsonStorage
from agno.tools.yfinance import YFinanceTools


def _get_thinking_agent(**kwargs):
    """Create an agent with thinking enabled using consistent settings."""
    default_config = {
        "model": Claude(
            id="claude-3-7-sonnet-20250219",
            thinking={"type": "enabled", "budget_tokens": 1024},
        ),
        "markdown": True,
        "telemetry": False,
        "monitoring": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def _get_interleaved_thinking_agent(**kwargs):
    """Create an agent with interleaved thinking enabled using Claude 4."""
    default_config = {
        "model": Claude(
            id="claude-sonnet-4-20250514",
            thinking={"type": "enabled", "budget_tokens": 2048},
            default_headers={"anthropic-beta": "interleaved-thinking-2025-05-14"},
        ),
        "markdown": True,
        "telemetry": False,
        "monitoring": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_thinking():
    agent = _get_thinking_agent()
    response: RunResponse = agent.run("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.thinking is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].thinking is not None


def test_thinking_stream():
    agent = _get_thinking_agent()
    response_stream = agent.run("Share a 2 sentence horror story", stream=True)

    # Verify it's an iterator
    assert hasattr(response_stream, "__iter__")

    responses = list(response_stream)
    assert len(responses) > 0
    for response in responses:
        assert response.content is not None or response.thinking is not None


@pytest.mark.asyncio
async def test_async_thinking():
    agent = _get_thinking_agent()
    response: RunResponse = await agent.arun("Share a 2 sentence horror story")

    assert response.content is not None
    assert response.thinking is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].thinking is not None


@pytest.mark.asyncio
async def test_async_thinking_stream():
    agent = _get_thinking_agent()
    response_stream = await agent.arun("Share a 2 sentence horror story", stream=True)

    # Verify it's an async iterator
    assert hasattr(response_stream, "__aiter__")

    responses = [response async for response in response_stream]
    assert len(responses) > 0
    for response in responses:
        assert response.content is not None or response.thinking is not None


def test_redacted_thinking():
    agent = _get_thinking_agent()
    # Testing string from anthropic
    response = agent.run(
        "ANTHROPIC_MAGIC_STRING_TRIGGER_REDACTED_THINKING_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
    )
    assert response.thinking is not None


def test_thinking_with_tool_calls():
    agent = _get_thinking_agent(tools=[YFinanceTools(cache_results=True)])

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage and thinking
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_redacted_thinking_with_tool_calls():
    agent = _get_thinking_agent(
        tools=[YFinanceTools(cache_results=True)],
        add_history_to_messages=True,
    )

    # Put a redacted thinking message in the history
    agent.run(
        "ANTHROPIC_MAGIC_STRING_TRIGGER_REDACTED_THINKING_46C9A13E193C177646C7398A98432ECCCE4C1253D5E2D82641AC0E52CC2876CB"
    )

    response = agent.run("What is the current price of TSLA?")

    # Verify tool usage
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert "TSLA" in response.content


def test_thinking_message_serialization():
    """Test that thinking content is properly serialized in Message objects."""
    message = Message(
        role="assistant",
        content="The answer is 42.",
        thinking="I need to think about the meaning of life. After careful consideration, 42 seems right.",
        provider_data={"signature": "thinking_sig_xyz789"},
    )

    # Serialize to dict
    message_dict = message.to_dict()

    # Verify thinking content is in the serialized data
    assert "thinking" in message_dict
    assert (
        message_dict["thinking"]
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
            model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
            storage=JsonStorage(dir_path=storage_dir),
            memory=Memory(),
            user_id="test_user",
            session_id="test_session",
            telemetry=False,
            monitoring=False,
        )

        # Ask a question that should trigger thinking
        response = await agent.arun("What is 25 * 47?", stream=False)

        # Verify response has thinking content
        assert response.thinking is not None
        assert len(response.thinking) > 0

        # Read the storage files to verify thinking was persisted
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_persisted = False
        for session_file in session_files:
            if session_file == "test_session.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                # Check messages in this session
                if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                    for run in session_data["memory"]["runs"]:
                        if "messages" in run:
                            for message in run["messages"]:
                                if message.get("role") == "assistant" and message.get("thinking"):
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
            model=Claude(id="claude-3-7-sonnet-20250219", thinking={"type": "enabled", "budget_tokens": 1024}),
            storage=JsonStorage(dir_path=storage_dir),
            memory=Memory(),
            user_id="test_user_stream",
            session_id="test_session_stream",
            telemetry=False,
            monitoring=False,
        )

        # Run with streaming
        stream_response = await agent.arun("What is 15 + 27?", stream=True)

        final_response = None
        async for chunk in stream_response:
            if hasattr(chunk, "thinking") and chunk.thinking:
                final_response = chunk

        # Verify we got thinking content
        assert final_response is not None
        assert final_response.thinking is not None

        # Verify storage contains the thinking content
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_found = False
        for session_file in session_files:
            if session_file == "test_session_stream.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                    for run in session_data["memory"]["runs"]:
                        if "messages" in run:
                            for message in run["messages"]:
                                if message.get("role") == "assistant" and message.get("thinking"):
                                    thinking_found = True
                                    break
                        if thinking_found:
                            break
                break

        assert thinking_found, "Thinking content from streaming should be stored"


# ============================================================================
# INTERLEAVED THINKING TESTS (Claude 4 specific)
# ============================================================================


def test_interleaved_thinking():
    """Test basic interleaved thinking functionality with Claude 4."""
    agent = _get_interleaved_thinking_agent()
    response: RunResponse = agent.run("What's 25 × 17? Think through it step by step.")

    assert response.content is not None
    assert response.thinking is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].thinking is not None


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
    has_thinking = any(r.thinking is not None for r in responses)

    assert has_content, "Should have content in responses"
    assert has_thinking, "Should have thinking in responses"


@pytest.mark.asyncio
async def test_async_interleaved_thinking():
    """Test async interleaved thinking."""
    agent = _get_interleaved_thinking_agent()
    response: RunResponse = await agent.arun("Calculate 15 × 23 and explain your reasoning.")

    assert response.content is not None
    assert response.thinking is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].thinking is not None


@pytest.mark.asyncio
async def test_async_interleaved_thinking_stream():
    """Test async streaming with interleaved thinking."""
    agent = _get_interleaved_thinking_agent()
    response_stream = await agent.arun("What's 37 × 19? Break it down step by step.", stream=True)

    # Verify it's an async iterator
    assert hasattr(response_stream, "__aiter__")

    responses = [response async for response in response_stream]
    assert len(responses) > 0

    # Should have both content and thinking in the responses
    has_content = any(r.content is not None for r in responses)
    has_thinking = any(r.thinking is not None for r in responses)

    assert has_content, "Should have content in responses"
    assert has_thinking, "Should have thinking in responses"


def test_interleaved_thinking_with_tools():
    """Test interleaved thinking with tool calls."""
    agent = _get_interleaved_thinking_agent(tools=[YFinanceTools(cache_results=True)])

    response = agent.run("What is the current price of AAPL? Think about why someone might want this information.")

    # Verify tool usage and thinking
    assert any(msg.tool_calls for msg in response.messages)
    assert response.content is not None
    assert response.thinking is not None
    assert "AAPL" in response.content


@pytest.mark.asyncio
async def test_interleaved_thinking_with_storage():
    """Test that interleaved thinking content is stored and retrievable."""
    with tempfile.TemporaryDirectory() as storage_dir:
        agent = Agent(
            model=Claude(
                id="claude-sonnet-4-20250514",
                thinking={"type": "enabled", "budget_tokens": 2048},
                default_headers={"anthropic-beta": "interleaved-thinking-2025-05-14"},
            ),
            storage=JsonStorage(dir_path=storage_dir),
            memory=Memory(),
            user_id="test_user_interleaved",
            session_id="test_session_interleaved",
            telemetry=False,
            monitoring=False,
        )

        # Ask a question that should trigger interleaved thinking
        response = await agent.arun("Calculate 144 ÷ 12 and show your thought process.", stream=False)

        # Verify response has thinking content
        assert response.thinking is not None
        assert len(response.thinking) > 0

        # Read the storage files to verify thinking was persisted
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_persisted = False
        for session_file in session_files:
            if session_file == "test_session_interleaved.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                # Check messages in this session
                if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                    for run in session_data["memory"]["runs"]:
                        if "messages" in run:
                            for message in run["messages"]:
                                if message.get("role") == "assistant" and message.get("thinking"):
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
                default_headers={"anthropic-beta": "interleaved-thinking-2025-05-14"},
            ),
            storage=JsonStorage(dir_path=storage_dir),
            memory=Memory(),
            user_id="test_user_interleaved_stream",
            session_id="test_session_interleaved_stream",
            telemetry=False,
            monitoring=False,
        )

        # Run with streaming
        stream_response = await agent.arun("What is 84 ÷ 7? Think through the division process.", stream=True)

        final_response = None
        async for chunk in stream_response:
            if hasattr(chunk, "thinking") and chunk.thinking:
                final_response = chunk

        # Verify we got thinking content
        assert final_response is not None
        assert final_response.thinking is not None

        # Verify storage contains the thinking content
        session_files = [f for f in os.listdir(storage_dir) if f.endswith(".json")]

        thinking_found = False
        for session_file in session_files:
            if session_file == "test_session_interleaved_stream.json":
                with open(os.path.join(storage_dir, session_file), "r") as f:
                    session_data = json.load(f)

                if "memory" in session_data and session_data["memory"] and "runs" in session_data["memory"]:
                    for run in session_data["memory"]["runs"]:
                        if "messages" in run:
                            for message in run["messages"]:
                                if message.get("role") == "assistant" and message.get("thinking"):
                                    thinking_found = True
                                    break
                        if thinking_found:
                            break
                break

        assert thinking_found, "Interleaved thinking content from streaming should be stored"


def test_interleaved_thinking_vs_regular_thinking():
    """Test that both regular and interleaved thinking work correctly and can be distinguished."""
    # Regular thinking agent
    regular_agent = _get_thinking_agent()
    regular_response = regular_agent.run("What is 5 × 6?")

    # Interleaved thinking agent
    interleaved_agent = _get_interleaved_thinking_agent()
    interleaved_response = interleaved_agent.run("What is 5 × 6?")

    # Both should have thinking content
    assert regular_response.thinking is not None
    assert interleaved_response.thinking is not None

    # Both should have content
    assert regular_response.content is not None
    assert interleaved_response.content is not None

    # Verify the models are different
    assert regular_agent.model.id == "claude-3-7-sonnet-20250219"
    assert interleaved_agent.model.id == "claude-sonnet-4-20250514"

    # Verify the headers are different
    assert not hasattr(regular_agent.model, "default_headers") or regular_agent.model.default_headers is None
    assert interleaved_agent.model.default_headers == {"anthropic-beta": "interleaved-thinking-2025-05-14"}
