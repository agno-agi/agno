from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from botocore.session import get_session
from botocore.validate import validate_parameters

from agno.models.aws import AwsBedrock
from agno.models.message import Message


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a value",
            "parameters": {"type": "object", "properties": {"key": {"type": "string"}}},
        },
    }
]
RESPONSE = {"output": {"message": {"role": "assistant", "content": [{"text": "hello"}]}}, "stopReason": "end_turn"}
CHOICES = [
    (None, None),
    ("auto", None),
    ("required", {"any": {}}),
    ({"type": "function", "function": {"name": "lookup"}}, {"tool": {"name": "lookup"}}),
    ("none", None),
    ({"type": "unknown"}, None),
    ({"type": "function", "function": None}, None),
    ({"type": "function", "function": {"name": 3}}, None),
]


class AsyncClient:
    def __init__(self):
        self.requests = []

    async def converse(self, **kwargs):
        self.requests.append(kwargs)
        return RESPONSE

    async def converse_stream(self, **kwargs):
        self.requests.append(kwargs)

        async def chunks():
            if False:
                yield {}

        return {"stream": chunks()}


def assert_request(request, choice, original_choice, tools, original_tools, expected):
    assert request["toolConfig"].get("toolChoice") == expected
    assert choice == original_choice
    assert tools == original_tools
    validate_parameters(
        request, get_session().get_service_model("bedrock-runtime").operation_model("Converse").input_shape
    )


@pytest.mark.parametrize("choice,expected", CHOICES)
@pytest.mark.parametrize("stream", [False, True])
def test_sync_tool_choice(choice, expected, stream):
    client = MagicMock()
    client.converse.return_value = RESPONSE
    client.converse_stream.return_value = {"stream": []}
    model = AwsBedrock(client=client)
    tools = deepcopy(TOOLS)
    original_tools, original_choice = deepcopy(tools), deepcopy(choice)
    kwargs = dict(
        messages=[Message(role="user", content="Use lookup")],
        assistant_message=Message(role="assistant"),
        tools=tools,
        tool_choice=choice,
    )
    if stream:
        list(model.invoke_stream(**kwargs))
        request = client.converse_stream.call_args.kwargs
    else:
        model.invoke(**kwargs)
        request = client.converse.call_args.kwargs
    assert_request(request, choice, original_choice, tools, original_tools, expected)


@pytest.mark.parametrize("choice,expected", CHOICES)
@pytest.mark.parametrize("stream", [False, True])
async def test_async_tool_choice(choice, expected, stream):
    client = AsyncClient()
    model = AwsBedrock(async_client=client)
    tools = deepcopy(TOOLS)
    original_tools, original_choice = deepcopy(tools), deepcopy(choice)
    kwargs = dict(
        messages=[Message(role="user", content="Use lookup")],
        assistant_message=Message(role="assistant"),
        tools=tools,
        tool_choice=choice,
    )
    if stream:
        async for _ in model.ainvoke_stream(**kwargs):
            pass
    else:
        await model.ainvoke(**kwargs)
    assert_request(client.requests[0], choice, original_choice, tools, original_tools, expected)


@pytest.mark.parametrize("choice,expected", CHOICES[2:4])
def test_agent_forwards_forced_tool_choice(choice, expected):
    from agno.agent import Agent

    client = MagicMock()
    client.converse.return_value = RESPONSE

    def lookup(key: str) -> str:
        """Look up a value."""
        return key

    Agent(model=AwsBedrock(client=client), tools=[lookup], tool_choice=choice, telemetry=False).run("Use lookup")
    assert client.converse.call_args.kwargs["toolConfig"]["toolChoice"] == expected


@pytest.mark.parametrize("choice", ["required", {"type": "function", "function": {"name": "lookup"}}])
def test_no_tools_preserves_absent_tool_config(choice):
    client = MagicMock()
    client.converse.return_value = RESPONSE
    AwsBedrock(client=client).invoke(
        messages=[Message(role="user", content="hello")],
        assistant_message=Message(role="assistant"),
        tool_choice=choice,
    )
    assert "toolConfig" not in client.converse.call_args.kwargs
