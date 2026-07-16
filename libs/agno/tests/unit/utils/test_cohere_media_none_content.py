"""Cohere format_messages must keep images when content is None (the default), and must
not emit a null text block. Same class as the openai/chat.py None-content media fix."""

from agno.media import Image
from agno.models.message import Message
from agno.utils.models.cohere import format_messages

# Bytes content avoids the helper's URL fetch (offline-safe).
_IMAGE = Image(content=b"\x89PNG_fake_bytes")


def _content(message):
    return format_messages([message])[0]["content"]


def test_none_content_with_image_keeps_image_and_empty_text():
    content = _content(Message(role="user", content=None, images=[_IMAGE]))

    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": ""}  # empty text, not None
    assert any(p.get("type") == "image_url" for p in content)


def test_str_content_with_image_unchanged():
    content = _content(Message(role="user", content="describe", images=[_IMAGE]))

    assert content[0] == {"type": "text", "text": "describe"}
    assert any(p.get("type") == "image_url" for p in content)
