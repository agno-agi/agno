from typing import Any, AsyncIterator, Iterator

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function, FunctionCall, UserInputField


class DummyModel(Model):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield ModelResponse()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def _hitl_function() -> Function:
    return Function(
        name="submit_comment",
        requires_user_input=True,
        user_input_schema=[UserInputField(name="content", field_type=str, description="Comment")],
    )


def _schema_values(response: ModelResponse) -> dict[str, str]:
    assert response.tool_executions is not None
    assert len(response.tool_executions) == 1
    schema = response.tool_executions[0].user_input_schema
    assert schema is not None
    return {field.name: field.value for field in schema}


def test_parallel_user_input_tool_calls_get_isolated_schema_values():
    function = _hitl_function()
    function_calls = [
        FunctionCall(function=function, arguments={"content": "first"}, call_id="call_1"),
        FunctionCall(function=function, arguments={"content": "second"}, call_id="call_2"),
    ]

    responses = list(DummyModel(id="dummy").run_function_calls(function_calls, function_call_results=[]))

    assert [response.event for response in responses] == [
        ModelResponseEvent.tool_call_paused.value,
        ModelResponseEvent.tool_call_paused.value,
    ]
    assert _schema_values(responses[0]) == {"content": "first"}
    assert _schema_values(responses[1]) == {"content": "second"}

    first_schema = responses[0].tool_executions[0].user_input_schema
    second_schema = responses[1].tool_executions[0].user_input_schema
    assert first_schema is not second_schema
    assert first_schema[0] is not second_schema[0]
    assert function.user_input_schema[0].value is None


@pytest.mark.asyncio
async def test_parallel_user_input_tool_calls_get_isolated_schema_values_async():
    function = _hitl_function()
    function_calls = [
        FunctionCall(function=function, arguments={"content": "first"}, call_id="call_1"),
        FunctionCall(function=function, arguments={"content": "second"}, call_id="call_2"),
    ]

    responses: list[ModelResponse] = []
    async for response in DummyModel(id="dummy").arun_function_calls(function_calls, function_call_results=[]):
        responses.append(response)

    assert [response.event for response in responses] == [
        ModelResponseEvent.tool_call_paused.value,
        ModelResponseEvent.tool_call_paused.value,
    ]
    assert _schema_values(responses[0]) == {"content": "first"}
    assert _schema_values(responses[1]) == {"content": "second"}

    first_schema = responses[0].tool_executions[0].user_input_schema
    second_schema = responses[1].tool_executions[0].user_input_schema
    assert first_schema is not second_schema
    assert first_schema[0] is not second_schema[0]
    assert function.user_input_schema[0].value is None
