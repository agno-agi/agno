"""AwsBedrock._format_messages must keep assistant narration text that accompanies a
tool call. The if/elif branch emitted only toolUse blocks, dropping the text on replay."""

from agno.models.aws import AwsBedrock
from agno.models.message import Message

MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"


def _content_blocks(message):
    model = AwsBedrock(id=MODEL_ID)
    formatted, _ = model._format_messages([message])
    return formatted[0]["content"]


def test_assistant_text_with_tool_call_is_preserved():
    message = Message(
        role="assistant",
        content="Let me check the weather for you.",
        tool_calls=[{"id": "t1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
    )

    blocks = _content_blocks(message)

    assert {"text": "Let me check the weather for you."} in blocks
    assert any("toolUse" in b for b in blocks)


def test_tool_call_without_text_adds_no_text_block():
    message = Message(
        role="assistant",
        content=None,
        tool_calls=[{"id": "t1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
    )

    blocks = _content_blocks(message)

    assert all("text" not in b for b in blocks)
    assert any("toolUse" in b for b in blocks)
