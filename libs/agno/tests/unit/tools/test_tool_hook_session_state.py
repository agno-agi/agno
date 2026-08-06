from typing import Any, Callable, Dict

import pytest

from agno.run.base import RunContext
from agno.tools.decorator import tool
from agno.tools.function import FunctionCall


def test_tool_hook_session_state_mutation_is_captured():
    """A tool_hook that mutates run_context.session_state must have its changes
    captured in updated_session_state, even when the tool function itself does
    not declare a run_context parameter (e.g. MCP tools). Regression for #9328."""

    def tool_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any], run_context: RunContext):
        calls = run_context.session_state.get("tool_call", [])
        calls.append({"tool_name": function_name, "args": arguments})
        run_context.session_state["tool_call"] = calls
        return function_call(**arguments)

    @tool(tool_hooks=[tool_hook])
    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    test_func.process_entrypoint()
    test_func._run_context = RunContext(run_id="r", session_id="s", session_state={"tool_call": []})

    result = FunctionCall(function=test_func, arguments={"param1": "value1"}).execute()

    assert result.status == "success"
    assert result.updated_session_state == {"tool_call": [{"tool_name": "test_func", "args": {"param1": "value1"}}]}


@pytest.mark.asyncio
async def test_tool_hook_session_state_mutation_is_captured_async():
    """Async counterpart of the #9328 regression."""

    async def tool_hook(
        function_name: str, function_call: Callable, arguments: Dict[str, Any], run_context: RunContext
    ):
        calls = run_context.session_state.get("tool_call", [])
        calls.append({"tool_name": function_name, "args": arguments})
        run_context.session_state["tool_call"] = calls
        return await function_call(**arguments)

    @tool(tool_hooks=[tool_hook])
    async def test_func(param1: str) -> str:
        return f"processed-{param1}"

    test_func.process_entrypoint()
    test_func._run_context = RunContext(run_id="r", session_id="s", session_state={"tool_call": []})

    result = await FunctionCall(function=test_func, arguments={"param1": "value1"}).aexecute()

    assert result.status == "success"
    assert result.updated_session_state == {"tool_call": [{"tool_name": "test_func", "args": {"param1": "value1"}}]}
