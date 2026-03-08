"""Tests for A2A streaming/non-streaming with Pydantic output_schema models.

Reproduces the bug from issue #6850: when an Agent has output_schema set to a
Pydantic model, the message:stream endpoint crashes with:
    TypeError: can only concatenate str (not "SomeModel") to str

The fix uses _serialize_content() which calls model_dump_json() on Pydantic
models instead of str().
"""

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.interfaces.a2a.utils import _serialize_content, map_run_output_to_a2a_task
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
    RunStatus,
)


# --- Test Pydantic model (simulates user's output_schema) ---


class AnalysisResult(BaseModel):
    sentiment: str = Field(description="Positive, negative, or neutral")
    confidence: float = Field(description="Confidence score 0-1")
    summary: str = Field(description="Brief summary")


# --- Unit tests for _serialize_content ---


def test_serialize_content_pydantic_model():
    """_serialize_content should JSON-serialize a Pydantic model."""
    model = AnalysisResult(sentiment="positive", confidence=0.95, summary="Great product")
    result = _serialize_content(model)
    parsed = json.loads(result)
    assert parsed["sentiment"] == "positive"
    assert parsed["confidence"] == 0.95
    assert parsed["summary"] == "Great product"


def test_serialize_content_string():
    """_serialize_content should pass through plain strings."""
    result = _serialize_content("hello world")
    assert result == "hello world"


def test_serialize_content_number():
    """_serialize_content should convert numbers via str()."""
    result = _serialize_content(42)
    assert result == "42"


def test_serialize_content_none_cast():
    """_serialize_content should handle None by converting to 'None'."""
    result = _serialize_content(None)
    assert result == "None"


# --- Integration tests: non-streaming (message:send) with output_schema ---


@pytest.fixture
def agent_with_schema():
    """Create an agent with output_schema set."""
    return Agent(name="analysis-agent", instructions="Analyze sentiment.")


@pytest.fixture
def test_client(agent_with_schema: Agent):
    agent_os = AgentOS(agents=[agent_with_schema], a2a_interface=True)
    app = agent_os.get_app()
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_message_send_with_pydantic_content(agent_with_schema: Agent, test_client):
    """message:send should serialize Pydantic model content to JSON text."""
    model_content = AnalysisResult(sentiment="positive", confidence=0.92, summary="Good")

    mock_output = RunOutput(
        run_id="run-1",
        session_id="ctx-1",
        agent_id=agent_with_schema.id,
        agent_name=agent_with_schema.name,
        content=model_content,
        status=RunStatus.completed,
    )

    with patch.object(agent_with_schema, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "req-schema-1",
            "params": {
                "message": {
                    "messageId": "msg-1",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Analyze this review"}],
                }
            },
        }

        response = test_client.post(
            f"/a2a/agents/{agent_with_schema.id}/v1/message:send", json=request_body
        )

        assert response.status_code == 200
        data = response.json()
        task = data["result"]

        history = task["history"]
        assert len(history) >= 1
        agent_msg = [m for m in history if m["role"] == "agent"]
        assert len(agent_msg) >= 1

        text_part = agent_msg[0]["parts"][0]["text"]
        parsed = json.loads(text_part)
        assert parsed["sentiment"] == "positive"
        assert parsed["confidence"] == 0.92


# --- Integration tests: streaming (message:stream) with output_schema ---


def test_message_stream_with_pydantic_content(agent_with_schema: Agent, test_client):
    """message:stream should not crash when event.content is a Pydantic model."""
    model_content = AnalysisResult(sentiment="negative", confidence=0.88, summary="Bad")

    async def mock_stream(*args, **kwargs) -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            run_id="run-stream-1",
            session_id="ctx-stream-1",
            agent_id=agent_with_schema.id,
        )
        yield RunContentEvent(
            run_id="run-stream-1",
            session_id="ctx-stream-1",
            agent_id=agent_with_schema.id,
            content=model_content,
        )
        yield RunCompletedEvent(
            run_id="run-stream-1",
            session_id="ctx-stream-1",
            agent_id=agent_with_schema.id,
            content=model_content,
        )

    with patch.object(agent_with_schema, "arun") as mock_arun:
        mock_arun.return_value = mock_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "req-stream-1",
            "params": {
                "message": {
                    "messageId": "msg-stream-1",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Analyze this"}],
                }
            },
        }

        response = test_client.post(
            f"/a2a/agents/{agent_with_schema.id}/v1/message:stream", json=request_body
        )

        assert response.status_code == 200

        events = response.text.strip().split("\n\n")
        has_message_event = False
        for event_block in events:
            if "event: Message" in event_block:
                has_message_event = True
                data_line = [l for l in event_block.split("\n") if l.startswith("data:")][0]
                data = json.loads(data_line[5:])
                text = data["result"]["parts"][0]["text"]
                parsed = json.loads(text)
                assert parsed["sentiment"] == "negative"
                assert parsed["confidence"] == 0.88

        assert has_message_event, "Expected at least one Message event in stream"


def test_message_stream_mixed_content(agent_with_schema: Agent, test_client):
    """message:stream should handle mixed string then Pydantic model content."""

    async def mock_stream(*args, **kwargs) -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            run_id="run-mix-1",
            session_id="ctx-mix-1",
            agent_id=agent_with_schema.id,
        )
        yield RunContentEvent(
            run_id="run-mix-1",
            session_id="ctx-mix-1",
            agent_id=agent_with_schema.id,
            content="Processing...",
        )
        yield RunCompletedEvent(
            run_id="run-mix-1",
            session_id="ctx-mix-1",
            agent_id=agent_with_schema.id,
            content=AnalysisResult(sentiment="neutral", confidence=0.5, summary="Meh"),
        )

    with patch.object(agent_with_schema, "arun") as mock_arun:
        mock_arun.return_value = mock_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "req-mix-1",
            "params": {
                "message": {
                    "messageId": "msg-mix-1",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Analyze"}],
                }
            },
        }

        response = test_client.post(
            f"/a2a/agents/{agent_with_schema.id}/v1/message:stream", json=request_body
        )

        assert response.status_code == 200


def test_map_run_output_with_pydantic_content():
    """map_run_output_to_a2a_task should serialize Pydantic content to valid JSON."""
    model_content = AnalysisResult(sentiment="positive", confidence=0.99, summary="Excellent")

    output = RunOutput(
        run_id="run-map-1",
        session_id="ctx-map-1",
        agent_id="agent-1",
        agent_name="test",
        content=model_content,
        status=RunStatus.completed,
    )

    task = map_run_output_to_a2a_task(output)

    assert task.history is not None
    assert len(task.history) > 0
    agent_msg = task.history[0]
    assert agent_msg.parts is not None
    assert len(agent_msg.parts) > 0
    text = agent_msg.parts[0].root.text
    parsed = json.loads(text)
    assert parsed["sentiment"] == "positive"
    assert parsed["confidence"] == 0.99
