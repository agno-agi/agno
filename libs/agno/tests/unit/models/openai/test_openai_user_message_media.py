"""User messages that carry media and no text, and user messages sent one after another.

Covers OpenAIChat._format_message / _format_all_messages and OpenAIResponses._format_messages.
OpenAI accepts two user messages in a row, so neither formatter merges them: each message is sent as its own item.
"""

import struct
import zlib
from typing import Any, Dict, List

import pytest

from agno.media import Audio, File, Image
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses


def _png_bytes() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


@pytest.fixture
def image() -> Image:
    return Image(content=_png_bytes(), format="png")


@pytest.fixture
def chat() -> OpenAIChat:
    return OpenAIChat(id="gpt-5.6-luna", api_key="test-key")


@pytest.fixture
def responses() -> OpenAIResponses:
    return OpenAIResponses(id="gpt-5.6-luna", api_key="test-key")


def _types(content: Any) -> List[str]:
    assert isinstance(content, list)
    return [part["type"] for part in content]


def _tool_exchange(call_id: str) -> List[Message]:
    return [
        Message(
            role="assistant",
            tool_calls=[{"id": call_id, "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id=call_id, content="result " + call_id),
    ]


# ---------------------------------------------------------------------------
# Chat Completions: media with no text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content", [None, []])
def test_chat_image_without_text_is_sent(chat: OpenAIChat, image: Image, content: Any):
    formatted = chat._format_message(Message(role="user", content=content, images=[image]))

    assert formatted["role"] == "user"
    assert _types(formatted["content"]) == ["image_url"]
    assert formatted["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("content", [None, []])
def test_chat_audio_without_text_is_sent(chat: OpenAIChat, content: Any):
    audio = Audio(content=b"abc", format="wav")
    formatted = chat._format_message(Message(role="user", content=content, audio=[audio]))

    assert _types(formatted["content"]) == ["input_audio"]


def test_chat_file_without_text_is_sent(chat: OpenAIChat):
    file = File(content=b"%PDF-1.4 x", mime_type="application/pdf", filename="a.pdf")
    formatted = chat._format_message(Message(role="user", files=[file]))

    assert _types(formatted["content"]) == ["file"]


def test_chat_image_and_file_without_text_are_both_sent(chat: OpenAIChat, image: Image):
    file = File(content=b"%PDF-1.4 x", mime_type="application/pdf", filename="a.pdf")
    formatted = chat._format_message(Message(role="user", images=[image], files=[file]))

    assert _types(formatted["content"]) == ["file", "image_url"]


def test_chat_message_with_text_and_image_is_unchanged(chat: OpenAIChat, image: Image):
    formatted = chat._format_message(Message(role="user", content="What is this?", images=[image]))

    assert _types(formatted["content"]) == ["text", "image_url"]
    assert formatted["content"][0] == {"type": "text", "text": "What is this?"}


def test_chat_empty_string_with_image_is_unchanged(chat: OpenAIChat, image: Image):
    formatted = chat._format_message(Message(role="user", content="", images=[image]))

    assert _types(formatted["content"]) == ["text", "image_url"]
    assert formatted["content"][0] == {"type": "text", "text": ""}


def test_chat_content_list_with_parts_is_sent_as_written(chat: OpenAIChat, image: Image):
    parts: List[Dict[str, Any]] = [{"type": "text", "text": "already built"}]
    formatted = chat._format_message(Message(role="user", content=parts, images=[image]))

    assert formatted["content"] == [{"type": "text", "text": "already built"}]


def test_chat_message_with_no_content_and_no_media_is_empty_string(chat: OpenAIChat):
    assert chat._format_message(Message(role="user"))["content"] == ""


def test_chat_unreadable_image_without_text_leaves_empty_string(chat: OpenAIChat):
    missing = Image(filepath="/nonexistent/photo.png")
    formatted = chat._format_message(Message(role="user", images=[missing]))

    assert formatted["content"] == ""


# ---------------------------------------------------------------------------
# Chat Completions: user messages in a row
# ---------------------------------------------------------------------------


def test_chat_note_then_text(chat: OpenAIChat):
    formatted = chat._format_all_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", content="Where is it?")]
    )

    assert formatted == [
        {"role": "user", "content": "Note: the order shipped."},
        {"role": "user", "content": "Where is it?"},
    ]


def test_chat_note_then_text_and_image(chat: OpenAIChat, image: Image):
    formatted = chat._format_all_messages(
        [
            Message(role="user", content="Note: the order shipped."),
            Message(role="user", content="Is this the box?", images=[image]),
        ]
    )

    assert formatted[0] == {"role": "user", "content": "Note: the order shipped."}
    assert formatted[1]["role"] == "user"
    assert _types(formatted[1]["content"]) == ["text", "image_url"]


def test_chat_note_then_image_only(chat: OpenAIChat, image: Image):
    formatted = chat._format_all_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", images=[image])]
    )

    assert formatted[0] == {"role": "user", "content": "Note: the order shipped."}
    assert formatted[1]["role"] == "user"
    assert _types(formatted[1]["content"]) == ["image_url"]


def test_chat_three_user_messages_in_a_row(chat: OpenAIChat, image: Image):
    formatted = chat._format_all_messages(
        [
            Message(role="user", content="one"),
            Message(role="user", images=[image]),
            Message(role="user", content="three"),
        ]
    )

    assert [m["role"] for m in formatted] == ["user", "user", "user"]
    assert formatted[0]["content"] == "one"
    assert _types(formatted[1]["content"]) == ["image_url"]
    assert formatted[2]["content"] == "three"


def test_chat_user_message_between_two_tool_results(chat: OpenAIChat, image: Image):
    formatted = chat._format_all_messages(
        [
            Message(role="user", content="start"),
            *_tool_exchange("call_1"),
            Message(role="user", images=[image]),
            *_tool_exchange("call_2"),
        ]
    )

    assert [m["role"] for m in formatted] == ["user", "assistant", "tool", "user", "assistant", "tool"]
    assert formatted[2]["tool_call_id"] == "call_1"
    assert _types(formatted[3]["content"]) == ["image_url"]
    assert formatted[5]["tool_call_id"] == "call_2"


# ---------------------------------------------------------------------------
# Responses: media with no text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content", [None, []])
def test_responses_image_without_text_is_sent(responses: OpenAIResponses, image: Image, content: Any):
    formatted = responses._format_messages([Message(role="user", content=content, images=[image])])

    assert len(formatted) == 1
    item = formatted[0]
    assert isinstance(item, dict)
    assert item["role"] == "user"
    assert _types(item["content"]) == ["input_image"]
    assert item["content"][0]["image_url"].startswith("data:image/png;base64,")


def test_responses_image_and_file_without_text_are_both_sent(responses: OpenAIResponses, image: Image):
    file = File(content=b"%PDF-1.4 x", mime_type="application/pdf", filename="a.pdf")
    formatted = responses._format_messages([Message(role="user", images=[image], files=[file])])

    assert isinstance(formatted[0], dict)
    assert _types(formatted[0]["content"]) == ["input_image", "input_file"]


def test_responses_message_with_text_and_image_is_unchanged(responses: OpenAIResponses, image: Image):
    formatted = responses._format_messages([Message(role="user", content="What is this?", images=[image])])

    assert isinstance(formatted[0], dict)
    assert _types(formatted[0]["content"]) == ["input_text", "input_image"]
    assert formatted[0]["content"][0] == {"type": "input_text", "text": "What is this?"}


def test_responses_empty_string_with_image_is_unchanged(responses: OpenAIResponses, image: Image):
    formatted = responses._format_messages([Message(role="user", content="", images=[image])])

    assert isinstance(formatted[0], dict)
    assert _types(formatted[0]["content"]) == ["input_text", "input_image"]
    assert formatted[0]["content"][0] == {"type": "input_text", "text": ""}


def test_responses_content_list_with_parts_is_sent_as_written(responses: OpenAIResponses, image: Image):
    parts: List[Dict[str, Any]] = [{"type": "input_text", "text": "already built"}]
    formatted = responses._format_messages([Message(role="user", content=parts, images=[image])])

    assert isinstance(formatted[0], dict)
    assert formatted[0]["content"] == [{"type": "input_text", "text": "already built"}]


# ---------------------------------------------------------------------------
# Responses: user messages in a row
# ---------------------------------------------------------------------------


def test_responses_note_then_text(responses: OpenAIResponses):
    formatted = responses._format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", content="Where is it?")]
    )

    assert formatted == [
        {"role": "user", "content": "Note: the order shipped."},
        {"role": "user", "content": "Where is it?"},
    ]


def test_responses_note_then_text_and_image(responses: OpenAIResponses, image: Image):
    formatted = responses._format_messages(
        [
            Message(role="user", content="Note: the order shipped."),
            Message(role="user", content="Is this the box?", images=[image]),
        ]
    )

    assert formatted[0] == {"role": "user", "content": "Note: the order shipped."}
    assert isinstance(formatted[1], dict)
    assert _types(formatted[1]["content"]) == ["input_text", "input_image"]


def test_responses_note_then_image_only(responses: OpenAIResponses, image: Image):
    formatted = responses._format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", images=[image])]
    )

    assert formatted[0] == {"role": "user", "content": "Note: the order shipped."}
    assert isinstance(formatted[1], dict)
    assert formatted[1]["role"] == "user"
    assert _types(formatted[1]["content"]) == ["input_image"]


def test_responses_three_user_messages_in_a_row(responses: OpenAIResponses, image: Image):
    formatted = responses._format_messages(
        [
            Message(role="user", content="one"),
            Message(role="user", images=[image]),
            Message(role="user", content="three"),
        ]
    )

    assert len(formatted) == 3
    assert all(isinstance(item, dict) and item["role"] == "user" for item in formatted)
    assert formatted[0]["content"] == "one"  # type: ignore[index]
    assert _types(formatted[1]["content"]) == ["input_image"]  # type: ignore[index]
    assert formatted[2]["content"] == "three"  # type: ignore[index]


def test_responses_user_message_between_two_tool_results(responses: OpenAIResponses, image: Image):
    formatted = responses._format_messages(
        [
            Message(role="user", content="start"),
            *_tool_exchange("call_1"),
            Message(role="user", images=[image]),
            *_tool_exchange("call_2"),
        ]
    )

    kinds = [item.get("type") or item.get("role") for item in formatted if isinstance(item, dict)]
    assert kinds == ["user", "function_call", "function_call_output", "user", "function_call", "function_call_output"]
    assert _types(formatted[3]["content"]) == ["input_image"]  # type: ignore[index]
