import importlib

import pytest

from agno.models.message import Message

_has_ollama = importlib.util.find_spec("ollama") is not None
_skip_ollama = pytest.mark.skipif(not _has_ollama, reason="ollama not installed")


def _assistant_with_arguments(arguments):
    return Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": arguments},
            }
        ],
    )


@_skip_ollama
def _format(arguments):
    from agno.models.ollama.chat import Ollama

    return Ollama()._format_message(_assistant_with_arguments(arguments))


@_skip_ollama
def test_format_message_accepts_empty_tool_arguments():
    formatted = _format("")
    assert formatted["tool_calls"][0]["function"]["arguments"] == {}


@_skip_ollama
def test_format_message_accepts_dict_tool_arguments():
    formatted = _format({"city": "London"})
    assert formatted["tool_calls"][0]["function"]["arguments"] == {"city": "London"}


@_skip_ollama
def test_format_message_accepts_null_tool_arguments():
    formatted = _format(None)
    assert formatted["tool_calls"][0]["function"]["arguments"] == {}


@_skip_ollama
def test_format_message_accepts_invalid_json_tool_arguments():
    formatted = _format("{not-json")
    assert formatted["tool_calls"][0]["function"]["arguments"] == {}
