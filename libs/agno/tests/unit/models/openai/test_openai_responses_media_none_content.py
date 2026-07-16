"""A user Message with images but content=None (the default) must still carry the
image through the Responses formatter. The str-only guard dropped it, leaving a
content-less message."""

from agno.media import Image
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def _image_parts(items):
    for item in items:
        content = item.get("content") if isinstance(item, dict) else None
        if isinstance(content, list):
            return [p for p in content if isinstance(p, dict) and p.get("type") == "input_image"]
    return []


def test_none_content_with_image_keeps_the_image():
    model = OpenAIResponses(id="gpt-4o")
    message = Message(role="user", content=None, images=[Image(url="https://example.com/x.png")])

    formatted = model._format_messages([message])

    assert len(_image_parts(formatted)) == 1
    assert formatted[0]["content"][0] == {"type": "input_text", "text": ""}


def test_str_content_with_image_unchanged():
    model = OpenAIResponses(id="gpt-4o")
    message = Message(role="user", content="describe", images=[Image(url="https://example.com/x.png")])

    formatted = model._format_messages([message])

    assert len(_image_parts(formatted)) == 1
    assert formatted[0]["content"][0] == {"type": "input_text", "text": "describe"}
