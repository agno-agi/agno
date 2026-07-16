"""DeepSeek._format_message must keep images/audio when content is None (the default).
Same class as the openai/chat.py None-content media fix."""

from agno.media import Image
from agno.models.deepseek.deepseek import DeepSeek
from agno.models.message import Message


def _image_parts(content):
    return [p for p in content if isinstance(p, dict) and p.get("type") == "image_url"]


def test_none_content_with_image_keeps_the_image():
    model = DeepSeek(id="deepseek-chat")
    formatted = model._format_message(Message(role="user", content=None, images=[Image(url="https://example.com/x.png")]))

    assert isinstance(formatted["content"], list)
    assert len(_image_parts(formatted["content"])) == 1
    assert {"type": "text", "text": ""} in formatted["content"]


def test_none_content_without_media_is_empty_string():
    model = DeepSeek(id="deepseek-chat")
    formatted = model._format_message(Message(role="user", content=None))
    assert formatted["content"] == ""
