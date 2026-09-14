"""Tool results that are falsy but meaningful (0, False, [], 0.0) must reach the
model as their string form on both the sync and the async execution paths."""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
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


def _function_call(return_value: Any) -> FunctionCall:
    def tool() -> Any:
        """Return a fixed value."""
        return return_value

    function = Function.from_callable(tool)
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id="call_1")


def _sync_tool_message(return_value: Any) -> Message:
    results: List[Message] = []
    for _ in _StubModel().run_function_call(_function_call(return_value), function_call_results=results):
        pass
    assert len(results) == 1
    return results[0]


async def _async_tool_message(return_value: Any) -> Message:
    results: List[Message] = []
    async for _ in _StubModel().arun_function_calls([_function_call(return_value)], function_call_results=results):
        pass
    assert len(results) == 1
    return results[0]


@pytest.mark.parametrize(
    "return_value, expected",
    [(0, "0"), (0.0, "0.0"), (False, "False"), ([], "[]"), ({}, "{}"), (1, "1"), ("text", "text")],
)
def test_sync_tool_result_keeps_falsy_values(return_value, expected):
    message = _sync_tool_message(return_value)
    assert message.role == "tool"
    assert message.content == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "return_value, expected",
    [(0, "0"), (0.0, "0.0"), (False, "False"), ([], "[]"), ({}, "{}"), (1, "1"), ("text", "text")],
)
async def test_async_tool_result_keeps_falsy_values(return_value, expected):
    message = await _async_tool_message(return_value)
    assert message.role == "tool"
    assert message.content == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("return_value", [0, False, [], "text"])
async def test_sync_and_async_tool_results_match(return_value):
    assert _sync_tool_message(return_value).content == (await _async_tool_message(return_value)).content
