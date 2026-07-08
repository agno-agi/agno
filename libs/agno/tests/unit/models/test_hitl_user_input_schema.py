import pytest

from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponseEvent
from agno.tools.function import Function, FunctionCall, UserInputField


def _hitl_function_calls():
    function = Function(
        name="submit_comment",
        requires_user_input=True,
        user_input_schema=[UserInputField(name="content", field_type=str, description="Comment")],
    )
    return [
        FunctionCall(function=function, arguments={"content": "first"}, call_id="call_1"),
        FunctionCall(function=function, arguments={"content": "second"}, call_id="call_2"),
    ], function


def _paused_tool_executions(responses):
    return [
        response.tool_executions[0] for response in responses if response.event == ModelResponseEvent.tool_call_paused
    ]


def test_parallel_hitl_function_calls_get_independent_user_input_schemas():
    model = OpenAIChat(id="gpt-4o", api_key="test")
    function_calls, function = _hitl_function_calls()

    responses = list(model.run_function_calls(function_calls, function_call_results=[]))
    paused_tools = _paused_tool_executions(responses)

    assert len(paused_tools) == 2
    assert paused_tools[0].user_input_schema is not paused_tools[1].user_input_schema
    assert paused_tools[0].user_input_schema[0] is not paused_tools[1].user_input_schema[0]
    assert paused_tools[0].user_input_schema[0].value == "first"
    assert paused_tools[1].user_input_schema[0].value == "second"
    assert function.user_input_schema[0].value is None


@pytest.mark.asyncio
async def test_parallel_hitl_function_calls_get_independent_user_input_schemas_async():
    model = OpenAIChat(id="gpt-4o", api_key="test")
    function_calls, function = _hitl_function_calls()

    responses = [response async for response in model.arun_function_calls(function_calls, function_call_results=[])]
    paused_tools = _paused_tool_executions(responses)

    assert len(paused_tools) == 2
    assert paused_tools[0].user_input_schema is not paused_tools[1].user_input_schema
    assert paused_tools[0].user_input_schema[0] is not paused_tools[1].user_input_schema[0]
    assert paused_tools[0].user_input_schema[0].value == "first"
    assert paused_tools[1].user_input_schema[0].value == "second"
    assert function.user_input_schema[0].value is None
