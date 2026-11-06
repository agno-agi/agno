import asyncio
from inspect import iscoroutine
from typing import Any, AsyncIterator, Iterator

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools.function import Function, FunctionCall


class StubModel(Model):
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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["coroutine", "task", "future", "custom"])
async def test_async_hook_dispatch_resolves_tool_output_before_messaging_and_caching(kind, tmp_path):
    created = []
    hook_results = []

    async def compute(value):
        await asyncio.sleep(0)
        return f"result:{value}"

    class CustomAwaitable:
        def __init__(self, value):
            self.value = value

        def __await__(self):
            return compute(self.value).__await__()

    def lookup(value: str):
        if kind == "future":
            result = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(result.set_result, f"result:{value}")
        elif kind == "custom":
            result = CustomAwaitable(value)
        else:
            result = compute(value)
            if kind == "task":
                result = asyncio.create_task(result)
        created.append(result)
        return result

    async def hook(function_name, function_call, arguments):
        result = await function_call(**arguments)
        hook_results.append(result)
        assert result == "result:hello"
        return result

    function = Function.from_callable(lookup)
    function.tool_hooks = [hook]
    function.cache_results = True
    function.cache_dir = str(tmp_path)
    model = StubModel()
    try:
        for _ in range(2):
            messages = []
            call = FunctionCall(function=function, arguments={"value": "hello"}, call_id="call_1")
            async for _ in model.arun_function_calls([call], function_call_results=messages):
                pass
            assert len(messages) == 1
            assert messages[0].role == "tool"
            assert messages[0].content == "result:hello"
            assert not messages[0].tool_call_error
        assert hook_results == ["result:hello", "result:hello"]
        assert len(created) == 1
    finally:
        for pending in created:
            if iscoroutine(pending):
                pending.close()
            elif isinstance(pending, asyncio.Future):
                await pending
