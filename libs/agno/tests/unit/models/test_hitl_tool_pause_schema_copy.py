"""Regression tests for HITL tool pause schema isolation."""

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function, FunctionCall, UserInputField


class _PausedHitlModel(Model):
    def __init__(self) -> None:
        super().__init__(id="paused-hitl", name="paused-hitl", provider="test")

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args, **kwargs):
        yield ModelResponse()

    async def ainvoke_stream(self, *args, **kwargs):
        yield ModelResponse()

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response) -> ModelResponse:
        return response


def _make_function() -> Function:
    return Function(
        name="submit_comment",
        requires_user_input=True,
        user_input_schema=[UserInputField(name="content", field_type=str, description="Comment content")],
    )


def _make_function_call(function: Function, call_id: str, content: str) -> FunctionCall:
    return FunctionCall(function=function, arguments={"content": content}, call_id=call_id)


def _assert_tool_pause_schema_isolation(responses):
    assert len(responses) == 2
    assert all(response.event == ModelResponseEvent.tool_call_paused.value for response in responses)

    first_schema = responses[0].tool_executions[0].user_input_schema
    second_schema = responses[1].tool_executions[0].user_input_schema

    assert first_schema is not None
    assert second_schema is not None
    assert first_schema is not second_schema
    assert [field.value for field in first_schema] == ["1"]
    assert [field.value for field in second_schema] == ["2"]


def test_sync_tool_pause_copies_user_input_schema():
    model = _PausedHitlModel()
    function = _make_function()
    function_calls = [
        _make_function_call(function, "call-1", "1"),
        _make_function_call(function, "call-2", "2"),
    ]

    responses = list(model.run_function_calls(function_calls, []))

    _assert_tool_pause_schema_isolation(responses)
    assert function.user_input_schema is not None
    assert [field.value for field in function.user_input_schema] == [None]


@pytest.mark.asyncio
async def test_async_tool_pause_copies_user_input_schema():
    model = _PausedHitlModel()
    function = _make_function()
    function_calls = [
        _make_function_call(function, "call-1", "1"),
        _make_function_call(function, "call-2", "2"),
    ]

    responses = [response async for response in model.arun_function_calls(function_calls, [])]

    _assert_tool_pause_schema_isolation(responses)
    assert function.user_input_schema is not None
    assert [field.value for field in function.user_input_schema] == [None]
