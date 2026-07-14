import json
import os
import tempfile

import pytest

from agno.agent import Agent
from agno.db.json import JsonDb
from agno.models.message import Message
from agno.models.ollama import Ollama
from agno.run.agent import RunOutput

api_key = os.getenv("OLLAMA_API_KEY")


def _get_thinking_agent(**kwargs):
    """Create an agent with thinking enabled using consistent settings."""
    # Use Ollama cloud if API key is available, otherwise skip test
    if not api_key:
        pytest.skip("OLLAMA_API_KEY not set - skipping Ollama cloud tests")

    default_config = {
        "model": Ollama(
            id="gpt-oss:120b",
            api_key=api_key,
        ),
        "markdown": True,
        "telemetry": False,
    }
    default_config.update(kwargs)
    return Agent(**default_config)


def test_thinking():
    agent = _get_thinking_agent()
    response: RunOutput = agent.run(
        "Share a 2 sentence horror story. Think through your creative process using <think></think> tags before writing the story."
    )

    assert response.content is not None
    assert response.reasoning_content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].reasoning_content is not None if response.messages is not None else False


@pytest.mark.asyncio
async def test_async_thinking():
    agent = _get_thinking_agent()
    response: RunOutput = await agent.arun(
        "Share a 2 sentence horror story. Think through your creative process using <think></think> tags before writing the story."
    )

    assert response.content is not None
    assert response.reasoning_content is not None
    assert response.messages is not None
    assert len(response.messages) == 3
    assert [m.role for m in response.messages] == ["system", "user", "assistant"]
    assert response.messages[2].reasoning_content is not None if response.messages is not None else False


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
        if not api_key:
            pytest.skip("OLLAMA_API_KEY not set - skipping Ollama cloud tests")

        agent = Agent(
            model=Ollama(id="gpt-oss:120b", api_key=api_key),
            db=JsonDb(db_path=storage_dir, session_table="test_session"),
            user_id="test_user",
            session_id="test_session",
            telemetry=False,
        )

        # Ask a question that should trigger thinking
        response = await agent.arun(
            "What is 25 * 47? Please think through the calculation step by step using <think></think> tags.",
            stream=False,
        )

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
