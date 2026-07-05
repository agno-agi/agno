from collections.abc import AsyncIterator, Iterator
from typing import Any

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.tools.function import Function, FunctionCall


class _TestModel(Model):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        return iter(())

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        if False:
            yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def _function_call(name: str, executed: list[str] | None = None) -> FunctionCall:
    def tool() -> str:
        if executed is not None:
            executed.append(name)
        return f"{name}-ok"

    function = Function.from_callable(tool, name=name)
    function.process_entrypoint()
    return FunctionCall(function=function, call_id=f"{name}-call", arguments={})


def test_tool_call_limit_results_are_marked_with_specific_flag() -> None:
    model = _TestModel(id="test-model", name="Test model")
    executed: list[str] = []
    results: list[Message] = []

    list(
        model.run_function_calls(
            function_calls=[
                _function_call("first", executed),
                _function_call("second", executed),
            ],
            function_call_results=results,
            function_call_limit=1,
        )
    )

    assert executed == ["first"]
    assert len(results) == 2
    assert results[0].tool_call_error is False
    assert results[0].tool_call_limit_reached is False
    assert results[1].tool_call_error is True
    assert results[1].tool_call_limit_reached is True


def test_limit_stop_guard_only_fires_when_all_results_are_limit_blocked() -> None:
    model = _TestModel(id="test-model", name="Test model")
    blocked_results: list[Message] = []

    list(
        model.run_function_calls(
            function_calls=[
                _function_call("first"),
                _function_call("second"),
            ],
            function_call_results=blocked_results,
            function_call_limit=0,
        )
    )

    assert model._all_tool_calls_blocked_by_limit(blocked_results) is True


def test_limit_stop_guard_does_not_fire_for_runtime_tool_errors() -> None:
    runtime_error_result = Message(
        role="tool",
        content="tool failed",
        tool_call_error=True,
        tool_call_limit_reached=False,
    )

    assert _TestModel._all_tool_calls_blocked_by_limit([runtime_error_result]) is False


def test_limit_stop_guard_does_not_fire_for_mixed_batches() -> None:
    successful_result = Message(role="tool", content="ok", tool_call_error=False)
    blocked_result = Message(
        role="tool",
        content="Tool call limit reached.",
        tool_call_error=True,
        tool_call_limit_reached=True,
    )

    assert _TestModel._all_tool_calls_blocked_by_limit([successful_result, blocked_result]) is False
