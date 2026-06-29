"""Propagation tests: finish_reason flows from ModelResponse to RunOutput / RunCompletedEvent.

Covers sync, async, streaming, team, the multi-step guard (an intermediate None must not wipe
the terminal reason), and the serialization round trip. No network: a mock model sets
finish_reason on its ModelResponse.
"""

import json
from typing import Any, AsyncIterator, Iterator, List, Optional
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.finish_reason import FinishReason
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent, RunOutput
from agno.team.team import Team


class MockModel(Model):
    """Model that returns a single ModelResponse carrying a configurable finish_reason."""

    def __init__(self, finish_reason: Optional[FinishReason] = FinishReason.STOP):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(
            content="Hello there",
            role="assistant",
            finish_reason=finish_reason,
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
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def test_finish_reason_propagates_to_run_output_sync():
    agent = Agent(model=MockModel(finish_reason=FinishReason.LENGTH))
    result = agent.run("hi")
    assert result.finish_reason == FinishReason.LENGTH


@pytest.mark.asyncio
async def test_finish_reason_propagates_to_run_output_async():
    agent = Agent(model=MockModel(finish_reason=FinishReason.LENGTH))
    result = await agent.arun("hi")
    assert result.finish_reason == FinishReason.LENGTH


def test_finish_reason_propagates_to_completed_event_stream():
    agent = Agent(model=MockModel(finish_reason=FinishReason.LENGTH))
    completed = [e for e in agent.run("hi", stream=True, stream_events=True) if isinstance(e, RunCompletedEvent)]
    assert len(completed) == 1
    assert completed[0].finish_reason == FinishReason.LENGTH


@pytest.mark.asyncio
async def test_finish_reason_propagates_to_completed_event_async_stream():
    agent = Agent(model=MockModel(finish_reason=FinishReason.LENGTH))
    completed = []
    async for e in agent.arun("hi", stream=True, stream_events=True):
        if isinstance(e, RunCompletedEvent):
            completed.append(e)
    assert len(completed) == 1
    assert completed[0].finish_reason == FinishReason.LENGTH


def test_finish_reason_propagates_to_team_run_output():
    member = Agent(name="member", model=MockModel(finish_reason=FinishReason.STOP))
    team = Team(members=[member], model=MockModel(finish_reason=FinishReason.LENGTH))
    result = team.run("hi")
    assert result.finish_reason == FinishReason.LENGTH


class MultiStepModel(MockModel):
    """Drives _process_model_response directly with a queue of provider responses."""

    def __init__(self, provider_responses: List[ModelResponse]):
        super().__init__()
        self._queue = list(provider_responses)

    def _invoke_with_retry(self, *args, **kwargs) -> ModelResponse:
        return self._queue.pop(0)

    def _populate_assistant_message(self, assistant_message: Message, provider_response: ModelResponse) -> Message:
        return assistant_message


def test_multi_step_terminal_reason_not_wiped_by_intermediate_step():
    """The aggregate model_response is reused across the tool loop; a later None must not wipe it."""
    model = MultiStepModel(
        provider_responses=[
            ModelResponse(content="a", finish_reason=FinishReason.TOOL_CALL),
            ModelResponse(content="b", finish_reason=None),  # intermediate step, no terminal reason
            ModelResponse(content="c", finish_reason=FinishReason.STOP),
        ]
    )
    aggregate = ModelResponse()
    assistant = Message(role="assistant")

    model._process_model_response(messages=[], assistant_message=assistant, model_response=aggregate)
    assert aggregate.finish_reason == FinishReason.TOOL_CALL

    model._process_model_response(messages=[], assistant_message=assistant, model_response=aggregate)
    assert aggregate.finish_reason == FinishReason.TOOL_CALL  # not wiped by the None step

    model._process_model_response(messages=[], assistant_message=assistant, model_response=aggregate)
    assert aggregate.finish_reason == FinishReason.STOP  # terminal reason wins


def test_run_output_finish_reason_serialization_round_trip():
    original = RunOutput(finish_reason=FinishReason.LENGTH)
    restored = RunOutput.from_dict(json.loads(json.dumps(original.to_dict())))
    assert restored.finish_reason == FinishReason.LENGTH
    assert isinstance(restored.finish_reason, FinishReason)
