"""A tool that streams several runs at once (a team delegating to all members
concurrently) must hand the model each run's content in one piece, not the
chunks in arrival order."""

from typing import Any, AsyncIterator, Callable, Iterator, List

import pytest

from agno.models.base import Model, _ToolOutputBuffer
from agno.models.message import Message
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


def _chunk(run_id: str, content: str) -> RunContentEvent:
    return RunContentEvent(run_id=run_id, content=content)


# Two members streaming at once: their chunks arrive interleaved.
INTERLEAVED = [
    _chunk("usage", "Runs rose"),
    _chunk("cost", "## Finding"),
    _chunk("usage", " to 243."),
    _chunk("cost", "\n\nLuna leads spend."),
]
EXPECTED = "Runs rose to 243.\n\n## Finding\n\nLuna leads spend."


def _function_call(tool: Callable) -> FunctionCall:
    function = Function.from_callable(tool)
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id="call_1")


def _sync_tool_message(items: List[Any]) -> Message:
    def delegate() -> Iterator[Any]:
        """Stream member events."""
        yield from items

    results: List[Message] = []
    for _ in _StubModel().run_function_call(_function_call(delegate), function_call_results=results):
        pass
    assert len(results) == 1
    return results[0]


async def _async_tool_message(items: List[Any]) -> Message:
    async def adelegate() -> AsyncIterator[Any]:
        """Stream member events."""
        for item in items:
            yield item

    results: List[Message] = []
    async for _ in _StubModel().arun_function_calls([_function_call(adelegate)], function_call_results=results):
        pass
    assert len(results) == 1
    return results[0]


def test_sync_tool_output_groups_interleaved_runs():
    assert _sync_tool_message(INTERLEAVED).content == EXPECTED


@pytest.mark.asyncio
async def test_async_tool_output_groups_interleaved_runs():
    assert (await _async_tool_message(INTERLEAVED)).content == EXPECTED


def test_single_run_output_is_unchanged():
    buffer = _ToolOutputBuffer()
    buffer.add_run_content("a", "Hello")
    buffer.add_run_content("a", ", world")
    assert buffer.getvalue() == "Hello, world"


def test_text_between_chunks_keeps_its_place():
    buffer = _ToolOutputBuffer()
    buffer.add_run_content("a", "before ")
    buffer.add_text("[event]")
    buffer.add_run_content("a", " after")
    assert buffer.getvalue() == "before [event] after"


def test_sequential_runs_are_separated():
    buffer = _ToolOutputBuffer()
    buffer.add_run_content("a", "First member.")
    buffer.add_run_content("b", "Second member.")
    buffer.add_text("Agent b: done")
    assert buffer.getvalue() == "First member.\n\nSecond member.Agent b: done"


def test_content_without_run_id_keeps_arrival_order():
    buffer = _ToolOutputBuffer()
    buffer.add_run_content(None, "x")
    buffer.add_run_content("a", "y")
    buffer.add_run_content(None, "z")
    assert buffer.getvalue() == "xyz"
