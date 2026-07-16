"""Mistral format_messages must keep tool_calls on an assistant turn that also has
reasoning_content; the reasoning branch used to win and flatten it to a UserMessage,
dropping the tool_calls and orphaning the following tool result."""

from agno.models.message import Message
from agno.utils.models._mistral_compat import AssistantMessage, UserMessage
from agno.utils.models.mistral import format_messages


def test_reasoning_with_tool_calls_keeps_tool_calls():
    assistant = Message(
        role="assistant",
        content="Let me check the weather.",
        reasoning_content="considering get_weather",
        tool_calls=[{"id": "abc123", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
    )

    formatted = format_messages([assistant])[0]

    assert isinstance(formatted, AssistantMessage)
    assert formatted.role == "assistant"
    assert formatted.tool_calls is not None and len(formatted.tool_calls) == 1


def test_reasoning_without_tool_calls_still_maps_to_user():
    assistant = Message(role="assistant", content="hmm", reasoning_content="thinking")

    formatted = format_messages([assistant])[0]

    assert isinstance(formatted, UserMessage)
