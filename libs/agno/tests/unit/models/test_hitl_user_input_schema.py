"""Parallel HITL calls to the same function must not share one user_input_schema.

The registered Function object is a singleton, so its user_input_schema used to be
mutated in place by every paused call: with two parallel calls to the same HITL
function, both paused ToolExecutions ended up pointing at the same schema with
last-write-wins values.
"""

from typing import AsyncIterator, Iterator, List

from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function, FunctionCall, UserInputField


class _StubModel(Model):
    """Minimal concrete Model; run_function_calls does not touch provider methods."""

    def invoke(self, *args, **kwargs) -> ModelResponse:  # pragma: no cover - unused
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:  # pragma: no cover - unused
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:  # pragma: no cover - unused
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:  # pragma: no cover - unused
        raise NotImplementedError

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:  # pragma: no cover - unused
        raise NotImplementedError

    def _parse_provider_response_delta(self, response) -> ModelResponse:  # pragma: no cover - unused
        raise NotImplementedError


def _make_hitl_function() -> Function:
    def submit_comment(content: str) -> str:  # pragma: no cover - never executed
        return content

    function = Function.from_callable(submit_comment)
    function.requires_user_input = True
    function.user_input_schema = [UserInputField(name="content", field_type=str, description="msg")]
    return function


def _paused_executions(model: _StubModel, function_calls: List[FunctionCall]) -> list:
    tool_executions = []
    for response in model.run_function_calls(function_calls=function_calls, function_call_results=[]):
        if (
            isinstance(response, ModelResponse)
            and response.event == ModelResponseEvent.tool_call_paused.value
            and response.tool_executions
        ):
            tool_executions.extend(response.tool_executions)
    return tool_executions


def test_parallel_hitl_calls_get_independent_user_input_schemas():
    model = _StubModel(id="stub")
    function = _make_hitl_function()

    calls = [
        FunctionCall(function=function, arguments={"content": "1"}, call_id="call_1"),
        FunctionCall(function=function, arguments={"content": "2"}, call_id="call_2"),
    ]

    executions = _paused_executions(model, calls)

    assert len(executions) == 2
    first, second = executions
    assert first.user_input_schema is not second.user_input_schema
    assert {f.name: f.value for f in first.user_input_schema} == {"content": "1"}
    assert {f.name: f.value for f in second.user_input_schema} == {"content": "2"}

    # The registered Function's own schema must stay untouched.
    assert function.user_input_schema is not None
    assert [f.value for f in function.user_input_schema] == [None]
