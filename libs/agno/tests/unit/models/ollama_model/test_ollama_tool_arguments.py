"""Ollama._format_message must not crash on a tool_call whose arguments are an empty
string or absent (a no-arg tool call from another provider replayed through Ollama)."""

import pytest

from agno.models.message import Message
from agno.models.ollama.chat import Ollama


def _arguments(tool_call_function):
    model = Ollama(id="llama3")
    message = Message(role="assistant", tool_calls=[{"id": "t1", "type": "function", "function": tool_call_function}])
    formatted = model._format_message(message)
    return formatted["tool_calls"][0]["function"]["arguments"]


@pytest.mark.parametrize(
    "function, expected",
    [
        ({"name": "w", "arguments": ""}, {}),  # empty string (was JSONDecodeError)
        ({"name": "w"}, {}),  # missing key (was KeyError)
        ({"name": "w", "arguments": '{"city": "Paris"}'}, {"city": "Paris"}),
        ({"name": "w", "arguments": {"x": 1}}, {"x": 1}),
    ],
)
def test_tool_call_arguments_are_robust(function, expected):
    assert _arguments(function) == expected
