"""User messages that carry media and no text, and user messages sent one after another.

Anthropic refuses a request that holds an empty text block. A user message with an image or a
document and no text must be sent as the media alone, on its own and after the same-role merge.
"""

import struct
import zlib
from typing import Any, List

import pytest

pytest.importorskip("anthropic")

from agno.media import File, Image
from agno.models.anthropic.claude import Claude as AnthropicClaude
from agno.models.message import Message
from agno.utils.models.claude import format_messages


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
def document() -> File:
    return File(content=b"plain text document", mime_type="text/plain", filename="a.txt")


def _types(content: Any) -> List[str]:
    assert isinstance(content, list)
    return [block["type"] for block in content]


def _assert_no_empty_text_block(chat_messages: List[Any]) -> None:
    for message in chat_messages:
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                assert block["text"], f"empty text block in {message['role']} message"


def _tool_exchange(call_id: str) -> List[Message]:
    return [
        Message(
            role="assistant",
            tool_calls=[{"id": call_id, "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id=call_id, content="result " + call_id),
    ]


@pytest.mark.parametrize("content", [None, [], ""])
def test_lone_image_only_message_has_no_text_block(image: Image, content: Any):
    chat_messages, _ = format_messages([Message(role="user", content=content, images=[image])])

    assert len(chat_messages) == 1
    assert chat_messages[0]["role"] == "user"
    assert _types(chat_messages[0]["content"]) == ["image"]


@pytest.mark.parametrize("content", [None, [], ""])
def test_lone_document_only_message_has_no_text_block(document: File, content: Any):
    chat_messages, _ = format_messages([Message(role="user", content=content, files=[document])])

    assert _types(chat_messages[0]["content"]) == ["document"]


def test_text_and_image_message_is_unchanged(image: Image):
    chat_messages, _ = format_messages([Message(role="user", content="What is this?", images=[image])])

    assert _types(chat_messages[0]["content"]) == ["text", "image"]
    assert chat_messages[0]["content"][0] == {"type": "text", "text": "What is this?"}


def test_note_then_text_merges_in_order():
    chat_messages, _ = format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", content="Where is it?")]
    )

    assert chat_messages == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Note: the order shipped."},
                {"type": "text", "text": "Where is it?"},
            ],
        }
    ]


def test_note_then_text_and_image_merges_in_order(image: Image):
    chat_messages, _ = format_messages(
        [
            Message(role="user", content="Note: the order shipped."),
            Message(role="user", content="Is this the box?", images=[image]),
        ]
    )

    assert len(chat_messages) == 1
    content = chat_messages[0]["content"]
    assert _types(content) == ["text", "text", "image"]
    assert [content[0]["text"], content[1]["text"]] == ["Note: the order shipped.", "Is this the box?"]  # type: ignore[index]


@pytest.mark.parametrize("content", [None, [], ""])
def test_note_then_image_only_merges_to_note_and_image(image: Image, content: Any):
    chat_messages, _ = format_messages(
        [
            Message(role="user", content="Note: the order shipped."),
            Message(role="user", content=content, images=[image]),
        ]
    )

    assert len(chat_messages) == 1
    merged = chat_messages[0]["content"]
    assert _types(merged) == ["text", "image"]
    assert merged[0] == {"type": "text", "text": "Note: the order shipped."}


def test_note_then_document_only_merges_to_note_and_document(document: File):
    chat_messages, _ = format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", files=[document])]
    )

    assert _types(chat_messages[0]["content"]) == ["text", "document"]


def test_image_only_then_text_keeps_earlier_message_first(image: Image):
    chat_messages, _ = format_messages(
        [Message(role="user", images=[image]), Message(role="user", content="What is this?")]
    )

    assert _types(chat_messages[0]["content"]) == ["image", "text"]


def test_three_user_messages_in_a_row(image: Image):
    chat_messages, _ = format_messages(
        [
            Message(role="user", content="one"),
            Message(role="user", images=[image]),
            Message(role="user", content="three"),
        ]
    )

    assert len(chat_messages) == 1
    content = chat_messages[0]["content"]
    assert _types(content) == ["text", "image", "text"]
    assert [content[0]["text"], content[2]["text"]] == ["one", "three"]  # type: ignore[index]


def test_image_only_user_message_between_two_tool_results(image: Image):
    chat_messages, _ = format_messages(
        [
            Message(role="user", content="start"),
            *_tool_exchange("toolu_1"),
            Message(role="user", images=[image]),
            *_tool_exchange("toolu_2"),
        ]
    )

    assert [m["role"] for m in chat_messages] == ["user", "assistant", "user", "assistant", "user"]
    assert _types(chat_messages[2]["content"]) == ["tool_result", "image"]
    assert _types(chat_messages[4]["content"]) == ["tool_result"]
    _assert_no_empty_text_block(chat_messages)


def test_merge_does_not_mutate_image_only_message(image: Image):
    note = Message(role="user", content="Note: the order shipped.")
    photo = Message(role="user", content=[], images=[image])
    original = photo.content

    format_messages([note, photo])
    format_messages([note, photo])

    assert photo.content is original
    assert photo.content == []


@pytest.mark.parametrize(
    "module_path",
    ["agno.models.aws.claude", "agno.models.azure.claude", "agno.models.vertexai.claude"],
)
def test_other_claude_providers_format_through_the_anthropic_class(module_path: str):
    """AWS, Azure and Vertex AI Claude build their messages in the inherited Anthropic request methods."""
    module = pytest.importorskip(module_path)

    for method in ("invoke", "ainvoke", "invoke_stream", "ainvoke_stream", "count_tokens", "acount_tokens"):
        assert getattr(module.Claude, method) is getattr(AnthropicClaude, method)


@pytest.mark.parametrize("content", [None, [], ""])
def test_user_message_with_no_text_and_no_media_keeps_its_turn(content: Any):
    """A turn replayed from history after its media was removed has no content left."""
    chat_messages, _ = format_messages(
        [
            Message(role="user", content=content),
            Message(role="assistant", content="It is a red square."),
            Message(role="user", content="What colour was it?"),
        ]
    )

    assert [m["role"] for m in chat_messages] == ["user", "assistant", "user"]
    assert chat_messages[0]["content"] == [{"type": "text", "text": "(no text)"}]
    assert chat_messages[2]["content"] == [{"type": "text", "text": "What colour was it?"}]


def test_empty_user_message_next_to_a_user_message_adds_nothing():
    chat_messages, _ = format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", content=None)]
    )

    assert chat_messages == [{"role": "user", "content": [{"type": "text", "text": "Note: the order shipped."}]}]


def test_empty_user_message_is_not_mutated():
    empty = Message(role="user", content=[])
    original = empty.content

    format_messages([empty])

    assert empty.content is original
    assert empty.content == []
