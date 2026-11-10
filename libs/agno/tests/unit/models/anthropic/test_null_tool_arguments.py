"""Claude request assembly must accept null or already-parsed tool arguments."""

import pytest

pytest.importorskip("anthropic")

from agno.models.message import Message
from agno.utils.models.claude import format_messages


def _tool_use_input(block):
    if isinstance(block, dict):
        return block.get("input")
    return getattr(block, "input", None)


def _tool_use_name(block):
    if isinstance(block, dict):
        return block.get("name")
    return getattr(block, "name", None)


def _assistant_with_arguments(arguments):
    return Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": "toolu_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": arguments},
            }
        ],
    )


def test_format_messages_accepts_null_tool_arguments():
    api_messages, _ = format_messages(
        [Message(role="user", content="hi"), _assistant_with_arguments(None)]
    )
    block = api_messages[1]["content"][0]
    assert _tool_use_name(block) == "get_weather"
    assert _tool_use_input(block) == {}


def test_format_messages_accepts_dict_tool_arguments():
    api_messages, _ = format_messages(
        [Message(role="user", content="hi"), _assistant_with_arguments({"city": "Paris"})]
    )
    block = api_messages[1]["content"][0]
    assert _tool_use_name(block) == "get_weather"
    assert _tool_use_input(block) == {"city": "Paris"}
