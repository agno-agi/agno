"""Tests for stop_reason propagation from ModelResponse to RunOutput.

Verifies fix for https://github.com/agno-agi/agno/issues/6179
"""

from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent, RunOutput


class MockModelWithStopReason(Model):
    def __init__(self, stop_reason: str = "end_turn"):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._stop_reason = stop_reason

        self._mock_response = ModelResponse(
            content="Test response content",
            role="assistant",
            stop_reason=stop_reason,
            response_usage=MessageMetrics(),
        )

        self.response = Mock(return_value=self._mock_response)
        self.aresponse = AsyncMock(return_value=self._mock_response)

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return await self.aresponse(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def test_stop_reason_end_turn_sync():
    """stop_reason='end_turn' should propagate to RunOutput."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="end_turn"))
    result = agent.run("Test message")

    assert result.stop_reason == "end_turn"


def test_stop_reason_max_tokens_sync():
    """stop_reason='max_tokens' should propagate to RunOutput."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="max_tokens"))
    result = agent.run("Test message")

    assert result.stop_reason == "max_tokens"


def test_stop_reason_tool_use_sync():
    """stop_reason='tool_use' should propagate to RunOutput."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="tool_use"))
    result = agent.run("Test message")

    assert result.stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_stop_reason_end_turn_async():
    """stop_reason='end_turn' should propagate to RunOutput in async."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="end_turn"))
    result = await agent.arun("Test message")

    assert result.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_stop_reason_max_tokens_async():
    """stop_reason='max_tokens' should propagate to RunOutput in async."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="max_tokens"))
    result = await agent.arun("Test message")

    assert result.stop_reason == "max_tokens"


def test_stop_reason_streaming_sync():
    """stop_reason should propagate in streaming mode."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="max_tokens"))

    final_output = None
    for chunk in agent.run("Test message", stream=True, yield_run_output=True):
        if isinstance(chunk, RunOutput):
            final_output = chunk

    assert final_output is not None
    assert final_output.stop_reason == "max_tokens"


@pytest.mark.asyncio
async def test_stop_reason_streaming_async():
    """stop_reason should propagate in async streaming mode."""
    agent = Agent(model=MockModelWithStopReason(stop_reason="max_tokens"))

    final_output = None
    async for chunk in agent.arun("Test message", stream=True, yield_run_output=True):
        if isinstance(chunk, RunOutput):
            final_output = chunk

    assert final_output is not None
    assert final_output.stop_reason == "max_tokens"
