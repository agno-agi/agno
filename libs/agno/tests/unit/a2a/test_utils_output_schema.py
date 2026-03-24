"""Tests for A2A streaming utilities with output_schema (Pydantic model content).

Regression test for:
  https://github.com/agno-agi/agno/issues/6850

When an Agent has ``output_schema`` set to a Pydantic BaseModel subclass, the
``RunContentEvent.content`` field contains a model instance rather than a plain
string.  The A2A streaming handler must serialise that instance to JSON before
concatenating it with ``accumulated_content`` (a ``str``), otherwise Python
raises::

    TypeError: can only concatenate str (not "<ModelClass>") to str
"""

import json
from typing import AsyncIterator, Union

import pytest
from pydantic import BaseModel

from agno.os.interfaces.a2a.utils import _serialize_content, stream_a2a_response
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunStartedEvent


# ---------------------------------------------------------------------------
# Helper: Pydantic model that simulates output_schema
# ---------------------------------------------------------------------------


class WeatherOutput(BaseModel):
    city: str
    temperature: float
    condition: str


# ---------------------------------------------------------------------------
# _serialize_content unit tests
# ---------------------------------------------------------------------------


class TestSerializeContent:
    """Unit tests for the _serialize_content helper."""

    def test_str_passthrough(self):
        assert _serialize_content("hello") == "hello"

    def test_pydantic_v2_model(self):
        model = WeatherOutput(city="Moscow", temperature=-5.0, condition="snow")
        result = _serialize_content(model)
        data = json.loads(result)
        assert data["city"] == "Moscow"
        assert data["temperature"] == -5.0

    def test_plain_dict(self):
        """Dicts are not Pydantic models; str() conversion is used as fallback."""
        result = _serialize_content({"key": "value"})
        assert "key" in result

    def test_integer(self):
        assert _serialize_content(42) == "42"


# ---------------------------------------------------------------------------
# stream_a2a_response integration-style test
# ---------------------------------------------------------------------------


async def _make_event_stream_with_pydantic_content() -> AsyncIterator:
    """Simulate agent events where content is a Pydantic model instance."""
    model_instance = WeatherOutput(city="Tokyo", temperature=22.5, condition="sunny")

    yield RunStartedEvent(run_id="run-1", session_id="session-1")
    # This is the problematic event: content is a Pydantic model, not a str
    yield RunContentEvent(run_id="run-1", session_id="session-1", content=model_instance)
    yield RunCompletedEvent(run_id="run-1", session_id="session-1", content=model_instance)


@pytest.mark.asyncio
async def test_stream_a2a_response_with_pydantic_output_schema():
    """stream_a2a_response must not raise TypeError when content is a Pydantic model.

    Regression test for issue #6850.
    """
    chunks = []
    async for chunk in stream_a2a_response(
        event_stream=_make_event_stream_with_pydantic_content(),
        request_id="req-test-1",
    ):
        chunks.append(chunk)

    # At minimum we expect: TaskStatusUpdateEvent (working), Message, TaskStatusUpdateEvent (completed), Task
    assert len(chunks) >= 3

    # The Message chunk must contain the serialised JSON of the Pydantic model
    message_chunks = [c for c in chunks if c.startswith("event: Message")]
    assert message_chunks, "Expected at least one Message event"

    message_data = json.loads(message_chunks[0].split("data: ", 1)[1].strip())
    text_part = message_data["result"]["parts"][0]["text"]

    # The text should be valid JSON containing the WeatherOutput fields
    parsed = json.loads(text_part)
    assert parsed["city"] == "Tokyo"
    assert parsed["temperature"] == 22.5
    assert parsed["condition"] == "sunny"
