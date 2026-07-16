"""A user Message with images/audio but content=None (the default) must still carry
the media. The str-only guard skipped media assembly, and the trailing None-handler
reset content to "", silently dropping the image."""

from agno.media import Image
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat


def _image_parts(content):
    return [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]


def test_none_content_with_image_keeps_the_image():
    model = OpenAIChat(id="gpt-4o")
    message = Message(role="user", content=None, images=[Image(url="https://example.com/x.png")])

    formatted = model._format_message(message)

    assert isinstance(formatted["content"], list)
    assert len(_image_parts(formatted["content"])) == 1
    # A text part is present with empty text (content was None).
    assert {"type": "text", "text": ""} in formatted["content"]


def test_str_content_with_image_unchanged():
    model = OpenAIChat(id="gpt-4o")
    message = Message(role="user", content="describe", images=[Image(url="https://example.com/x.png")])

    formatted = model._format_message(message)

    assert {"type": "text", "text": "describe"} in formatted["content"]
    assert len(_image_parts(formatted["content"])) == 1


def test_none_content_without_media_is_empty_string():
    model = OpenAIChat(id="gpt-4o")
    formatted = model._format_message(Message(role="user", content=None))
    assert formatted["content"] == ""
