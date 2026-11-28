"""A generator tool with ``show_result=True`` yields a ``ModelResponse`` and then
the event itself on the sync path.

Both async branches used to ``continue`` right after putting the response, so the
``RunContentEvent`` never reached the caller's stream: a Team in route mode
streamed its member's content with ``run()`` but not with ``arun()``.
"""

import asyncio
from typing import Any, AsyncIterator, Iterator, List

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunContentEvent
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


def _sync_generator_call() -> FunctionCall:
    def tool() -> Iterator[RunContentEvent]:
        """Stream one result."""
        yield RunContentEvent(content="a")

    function = Function.from_callable(tool)
    function.show_result = True
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id="call_1")


def _async_generator_call() -> FunctionCall:
    async def tool() -> AsyncIterator[RunContentEvent]:
        """Stream one result."""
        yield RunContentEvent(content="a")

    function = Function.from_callable(tool)
    function.show_result = True
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id="call_1")


def _response_before_event(events: List[Any]) -> None:
    """Assert the tool's content is sent once, and its event follows it."""
    response_at = next(
        i for i, e in enumerate(events) if isinstance(e, ModelResponse) and e.content == "a"
    )
    event_at = next(i for i, e in enumerate(events) if isinstance(e, RunContentEvent) and e.content == "a")
    assert response_at < event_at


def test_sync_path_keeps_the_event():
    events = list(_StubModel().run_function_calls([_sync_generator_call()], function_call_results=[]))

    _response_before_event(events)


def test_async_generator_path_keeps_the_event():
    async def collect() -> List[Any]:
        return [e async for e in _StubModel().arun_function_calls([_async_generator_call()], function_call_results=[])]

    _response_before_event(asyncio.run(collect()))


def test_sync_generator_on_the_async_path_keeps_the_event():
    async def collect() -> List[Any]:
        return [e async for e in _StubModel().arun_function_calls([_sync_generator_call()], function_call_results=[])]

    _response_before_event(asyncio.run(collect()))
