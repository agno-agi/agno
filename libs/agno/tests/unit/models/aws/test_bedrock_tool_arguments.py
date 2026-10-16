import importlib

import pytest

from agno.models.message import Message

_has_boto3 = importlib.util.find_spec("boto3") is not None
_skip_boto3 = pytest.mark.skipif(not _has_boto3, reason="boto3 not installed")


def _assistant_with_arguments(arguments):
    return Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": "tooluse_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": arguments},
            }
        ],
    )


@_skip_boto3
def _format(messages):
    from agno.models.aws.bedrock import AwsBedrock

    model = AwsBedrock(
        id="mistral.mistral-small-2402-v1:0",
        aws_region="us-east-1",
        append_trailing_user_message=False,
    )
    formatted, _ = model._format_messages(messages)
    return formatted


@_skip_boto3
def test_format_messages_accepts_dict_tool_arguments():
    formatted = _format(
        [
            Message(role="user", content="weather in London"),
            _assistant_with_arguments({"city": "London"}),
        ]
    )

    tool_use = formatted[-1]["content"][0]["toolUse"]
    assert tool_use["name"] == "get_weather"
    assert tool_use["input"] == {"city": "London"}


@_skip_boto3
def test_format_messages_accepts_null_tool_arguments():
    formatted = _format(
        [
            Message(role="user", content="weather in London"),
            _assistant_with_arguments(None),
        ]
    )

    tool_use = formatted[-1]["content"][0]["toolUse"]
    assert tool_use["input"] == {}


@_skip_boto3
def test_format_messages_accepts_empty_string_tool_arguments():
    formatted = _format(
        [
            Message(role="user", content="weather in London"),
            _assistant_with_arguments(""),
        ]
    )

    tool_use = formatted[-1]["content"][0]["toolUse"]
    assert tool_use["input"] == {}
