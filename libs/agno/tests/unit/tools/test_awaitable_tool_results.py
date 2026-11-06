import asyncio
from inspect import isasyncgen, iscoroutine, isgenerator

import pytest

from agno.tools.function import Function, FunctionCall


@pytest.fixture(params=[None, "empty", "sync", "async"])
def tool_hooks(request):
    def sync_hook(function_name, function_call, arguments):
        return function_call(**arguments)

    async def async_hook(function_name, function_call, arguments):
        result = await function_call(**arguments)
        # A hook must receive the resolved value, not another awaitable.
        assert isinstance(result, str)
        return result

    return {None: None, "empty": [], "sync": [sync_hook], "async": [async_hook]}[request.param]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["coroutine", "task", "future", "custom"])
async def test_sync_entrypoint_awaitable_is_resolved(kind, tool_hooks):
    created = []
    completed = []

    async def compute(value):
        await asyncio.sleep(0)
        completed.append(value)
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

    function = Function.from_callable(lookup)
    function.tool_hooks = tool_hooks
    call = FunctionCall(function=function, arguments={"value": "hello"})
    try:
        result = await call.aexecute()
        assert result.status == "success"
        assert result.result == "result:hello"
        assert call.result == "result:hello"
        if kind != "future":
            assert completed == ["hello"]
    finally:
        # Keep a failing regression run free of leaked coroutines/tasks.
        for pending in created:
            if iscoroutine(pending):
                pending.close()
            elif isinstance(pending, asyncio.Future):
                await pending


@pytest.mark.asyncio
async def test_sync_entrypoint_awaitable_failure_is_reported(tool_hooks):
    created = []

    async def fail():
        raise ValueError("tool failed")

    def lookup():
        result = fail()
        created.append(result)
        return result

    function = Function.from_callable(lookup)
    function.tool_hooks = tool_hooks
    try:
        result = await FunctionCall(function=function).aexecute()
        assert result.status == "failure"
        assert result.error == "tool failed"
    finally:
        for pending in created:
            pending.close()


@pytest.mark.asyncio
async def test_sync_entrypoint_caches_resolved_value(tool_hooks, tmp_path):
    executions = []
    created = []

    async def compute(value):
        executions.append(value)
        return f"result:{value}"

    def lookup(value: str):
        result = compute(value)
        created.append(result)
        return result

    function = Function.from_callable(lookup)
    function.tool_hooks = tool_hooks
    function.cache_results = True
    function.cache_dir = str(tmp_path)
    try:
        for _ in range(2):
            result = await FunctionCall(function=function, arguments={"value": "hello"}).aexecute()
            assert result.status == "success"
            assert result.result == "result:hello"
        assert executions == ["hello"]
        assert len(created) == 1
    finally:
        for pending in created:
            pending.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("hooks", [None, [], "passthrough"])
async def test_generator_results_remain_lazy(asynchronous, hooks):
    consumed = []

    def sync_stream():
        consumed.append("read")
        yield "chunk"

    async def async_stream():
        consumed.append("read")
        yield "chunk"

    async def passthrough(function_name, function_call, arguments):
        return await function_call(**arguments)

    function = Function.from_callable(async_stream if asynchronous else sync_stream)
    function.tool_hooks = [passthrough] if hooks == "passthrough" else hooks
    result = await FunctionCall(function=function).aexecute()
    assert result.status == "success"
    assert consumed == []
    if asynchronous:
        assert isasyncgen(result.result)
        assert [chunk async for chunk in result.result] == ["chunk"]
    else:
        assert isgenerator(result.result)
        assert list(result.result) == ["chunk"]
    assert consumed == ["read"]
