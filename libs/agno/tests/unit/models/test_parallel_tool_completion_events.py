import asyncio
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function, FunctionCall


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


def _function_call(tool, call_id: str, show_result: bool = False) -> FunctionCall:
    function = Function.from_callable(tool)
    function.show_result = show_result
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id=call_id)


def _tool_call_id(event: ModelResponse) -> str:
    assert event.tool_executions is not None
    assert len(event.tool_executions) == 1
    assert event.tool_executions[0].tool_call_id is not None
    return event.tool_executions[0].tool_call_id


@pytest.mark.asyncio
async def test_parallel_tool_completion_events_are_streamed_as_each_tool_finishes():
    slow_started = asyncio.Event()
    fast_started = asyncio.Event()
    slow_can_finish = asyncio.Event()
    fast_can_finish = asyncio.Event()
    fast_finished = asyncio.Event()

    async def slow_tool() -> str:
        """Wait until the test allows this tool to finish."""
        slow_started.set()
        await slow_can_finish.wait()
        return "slow done"

    async def fast_tool() -> str:
        """Wait until the test allows this tool to finish."""
        fast_started.set()
        await fast_can_finish.wait()
        fast_finished.set()
        return "fast done"

    function_call_results: List[Message] = []
    stream = _StubModel().arun_function_calls(
        [
            _function_call(slow_tool, "slow-call"),
            _function_call(fast_tool, "fast-call"),
        ],
        function_call_results,
    )

    started_events = [await stream.__anext__(), await stream.__anext__()]
    assert [event.event for event in started_events] == [
        ModelResponseEvent.tool_call_started.value,
        ModelResponseEvent.tool_call_started.value,
    ]

    first_completion_task = asyncio.create_task(stream.__anext__())
    await asyncio.gather(slow_started.wait(), fast_started.wait())
    fast_can_finish.set()
    await fast_finished.wait()

    for _ in range(20):
        if first_completion_task.done():
            break
        await asyncio.sleep(0)
    fast_completion_was_streamed = first_completion_task.done()

    slow_can_finish.set()
    first_completion = await asyncio.wait_for(first_completion_task, timeout=1)
    second_completion = await asyncio.wait_for(stream.__anext__(), timeout=1)
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()

    assert fast_completion_was_streamed
    assert [first_completion.event, second_completion.event] == [
        ModelResponseEvent.tool_call_completed.value,
        ModelResponseEvent.tool_call_completed.value,
    ]
    assert [_tool_call_id(first_completion), _tool_call_id(second_completion)] == ["fast-call", "slow-call"]
    assert [message.tool_call_id for message in function_call_results] == ["slow-call", "fast-call"]


@pytest.mark.asyncio
async def test_async_generator_tool_events_remain_streamed_while_another_tool_runs():
    generator_started = asyncio.Event()
    generator_can_finish = asyncio.Event()
    slow_started = asyncio.Event()
    slow_can_finish = asyncio.Event()

    async def streaming_tool() -> AsyncIterator[str]:
        """Yield output before waiting for the test to finish the tool."""
        generator_started.set()
        yield "first chunk"
        await generator_can_finish.wait()
        yield "last chunk"

    async def slow_tool() -> str:
        """Wait until the test allows this tool to finish."""
        slow_started.set()
        await slow_can_finish.wait()
        return "slow done"

    function_call_results: List[Message] = []
    stream = _StubModel().arun_function_calls(
        [
            _function_call(streaming_tool, "streaming-call", show_result=True),
            _function_call(slow_tool, "slow-call"),
        ],
        function_call_results,
    )

    await stream.__anext__()
    await stream.__anext__()
    first_streamed_output_task = asyncio.create_task(stream.__anext__())
    await asyncio.gather(generator_started.wait(), slow_started.wait())
    first_streamed_output = await asyncio.wait_for(first_streamed_output_task, timeout=1)

    assert first_streamed_output.content == "first chunk"
    assert not slow_can_finish.is_set()

    generator_can_finish.set()
    last_streamed_output = await asyncio.wait_for(stream.__anext__(), timeout=1)
    generator_completion = await asyncio.wait_for(stream.__anext__(), timeout=1)
    assert last_streamed_output.content == "last chunk"
    assert _tool_call_id(generator_completion) == "streaming-call"
    assert not slow_can_finish.is_set()

    slow_can_finish.set()
    slow_completion = await asyncio.wait_for(stream.__anext__(), timeout=1)
    assert _tool_call_id(slow_completion) == "slow-call"
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    assert [message.tool_call_id for message in function_call_results] == ["streaming-call", "slow-call"]


@pytest.mark.asyncio
async def test_cancelling_completion_stream_cancels_tool_tasks_even_if_tool_swallows_cancellation():
    tool_started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    never_finish = asyncio.Event()

    async def cancellation_swallowing_tool() -> str:
        """Record cancellation but deliberately return instead of re-raising it."""
        tool_started.set()
        try:
            await never_finish.wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            return "cancelled"

    stream = _StubModel().arun_function_calls(
        [_function_call(cancellation_swallowing_tool, "cancel-call")],
        [],
    )
    await stream.__anext__()
    completion_task = asyncio.create_task(stream.__anext__())
    await tool_started.wait()

    completion_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await completion_task

    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
