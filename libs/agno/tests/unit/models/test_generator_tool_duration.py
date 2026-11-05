"""A tool that returns a generator does its work while the generator is consumed, so its recorded
duration must cover the consumption on both the sync and the async execution paths."""

import asyncio
import time
from typing import Any, AsyncIterator, Callable, Iterator, List

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function, FunctionCall

_WORK_SECONDS = 0.05
_SLOW_SECONDS = 0.5


class _StubModel(Model):
    def __init__(self):
        super().__init__(id="stub", name="stub", provider="stub")

    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


def sync_generator_tool() -> Iterator[str]:
    """Do the work while being consumed."""
    time.sleep(_WORK_SECONDS)
    yield "done"


async def async_generator_tool() -> AsyncIterator[str]:
    """Do the work while being consumed."""
    await asyncio.sleep(_WORK_SECONDS)
    yield "done"


async def slow_tool() -> str:
    """Do the work before returning."""
    await asyncio.sleep(_SLOW_SECONDS)
    return "done"


def _function_call(tool: Callable, call_id: str = "call_1") -> FunctionCall:
    function = Function.from_callable(tool)
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id=call_id)


def _completed_duration(responses: List[Any], call_id: str = "call_1") -> float:
    completed = [
        r.tool_executions[0]
        for r in responses
        if getattr(r, "event", None) == ModelResponseEvent.tool_call_completed.value
        and r.tool_executions[0].tool_call_id == call_id
    ]
    assert len(completed) == 1
    return completed[0].metrics.duration


def test_sync_generator_tool_duration_covers_consumption():
    """Verify that a sync generator's duration on the sync path covers its consumption."""
    results: List[Message] = []
    responses = list(_StubModel().run_function_call(_function_call(sync_generator_tool), function_call_results=results))
    assert _completed_duration(responses) >= _WORK_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [sync_generator_tool, async_generator_tool])
async def test_async_generator_tool_duration_covers_consumption(tool):
    """Verify that a generator's duration on the async path covers its consumption."""
    results: List[Message] = []
    responses = [
        r async for r in _StubModel().arun_function_calls([_function_call(tool)], function_call_results=results)
    ]
    assert _completed_duration(responses) >= _WORK_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [sync_generator_tool, async_generator_tool])
async def test_async_generator_tool_duration_excludes_rest_of_batch(tool):
    """Verify that a generator run alongside a slow tool is not timed while waiting for that tool."""
    results: List[Message] = []
    function_calls = [_function_call(slow_tool, call_id="call_slow"), _function_call(tool, call_id="call_generator")]
    responses = [r async for r in _StubModel().arun_function_calls(function_calls, function_call_results=results)]
    assert _completed_duration(responses, call_id="call_slow") >= _SLOW_SECONDS
    generator_duration = _completed_duration(responses, call_id="call_generator")
    assert _WORK_SECONDS <= generator_duration < _SLOW_SECONDS
