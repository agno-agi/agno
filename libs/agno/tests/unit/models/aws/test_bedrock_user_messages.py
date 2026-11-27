"""User messages sent one after another, and user messages that carry media and no text.

AwsBedrock._format_messages builds the Converse `messages` list for the sync and the async request
methods. Converse models with strict templates refuse two user turns in a row, so user messages in
a row are sent as one user turn. A turn of tool results stays a turn of its own.
"""

import struct
import zlib
from typing import Any, Dict, List

import pytest

pytest.importorskip("boto3")

from agno.media import Image
from agno.models.aws import AwsBedrock
from agno.models.message import Message


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
def model() -> AwsBedrock:
    return AwsBedrock(id="amazon.nova-lite-v1:0")


def _kinds(turn: Dict[str, Any]) -> List[str]:
    return [next(iter(block)) for block in turn["content"]]


def _assert_no_empty_text_block(turns: List[Dict[str, Any]]) -> None:
    for turn in turns:
        for block in turn["content"]:
            if "text" in block:
                assert block["text"], f"empty text block in {turn['role']} turn"


def _tool_exchange(call_id: str) -> List[Message]:
    return [
        Message(
            role="assistant",
            tool_calls=[{"id": call_id, "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id=call_id, content="result " + call_id),
    ]


@pytest.mark.parametrize("content", [None, ""])
def test_lone_image_only_message_has_no_text_block(model: AwsBedrock, image: Image, content: Any):
    turns, _ = model._format_messages([Message(role="user", content=content, images=[image])])

    assert len(turns) == 1
    assert turns[0]["role"] == "user"
    assert _kinds(turns[0]) == ["image"]
    assert turns[0]["content"][0]["image"]["format"] == "png"


def test_lone_text_and_image_message_is_unchanged(model: AwsBedrock, image: Image):
    turns, _ = model._format_messages([Message(role="user", content="What is this?", images=[image])])

    assert _kinds(turns[0]) == ["text", "image"]
    assert turns[0]["content"][0] == {"text": "What is this?"}


def test_note_then_text_is_one_user_turn(model: AwsBedrock):
    turns, _ = model._format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", content="Where is it?")]
    )

    assert turns == [{"role": "user", "content": [{"text": "Note: the order shipped."}, {"text": "Where is it?"}]}]


def test_note_then_text_and_image_is_one_user_turn(model: AwsBedrock, image: Image):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="Note: the order shipped."),
            Message(role="user", content="Is this the box?", images=[image]),
        ]
    )

    assert len(turns) == 1
    assert _kinds(turns[0]) == ["text", "text", "image"]
    assert [turns[0]["content"][0]["text"], turns[0]["content"][1]["text"]] == [
        "Note: the order shipped.",
        "Is this the box?",
    ]


@pytest.mark.parametrize("content", [None, "", []])
def test_note_then_image_only_is_note_and_image(model: AwsBedrock, image: Image, content: Any):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="Note: the order shipped."),
            Message(role="user", content=content, images=[image]),
        ]
    )

    assert len(turns) == 1
    assert _kinds(turns[0]) == ["text", "image"]
    assert turns[0]["content"][0] == {"text": "Note: the order shipped."}


def test_three_user_messages_in_a_row_are_one_turn_in_order(model: AwsBedrock, image: Image):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="one"),
            Message(role="user", images=[image]),
            Message(role="user", content="three"),
        ]
    )

    assert len(turns) == 1
    assert _kinds(turns[0]) == ["text", "image", "text"]
    assert [turns[0]["content"][0]["text"], turns[0]["content"][2]["text"]] == ["one", "three"]


def test_user_messages_after_an_assistant_turn_merge_with_each_other_only(model: AwsBedrock):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="first"),
            Message(role="assistant", content="reply"),
            Message(role="user", content="note"),
            Message(role="user", content="question"),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == [{"text": "first"}]
    assert turns[2]["content"] == [{"text": "note"}, {"text": "question"}]


def test_tool_results_are_grouped_as_before(model: AwsBedrock):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="start"),
            Message(
                role="assistant",
                tool_calls=[
                    {"id": "t1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}},
                    {"id": "t2", "type": "function", "function": {"name": "lookup", "arguments": "{}"}},
                ],
            ),
            Message(role="tool", tool_call_id="t1", content="one"),
            Message(role="tool", tool_call_id="t2", content="two"),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    assert _kinds(turns[2]) == ["toolResult", "toolResult"]
    assert [block["toolResult"]["toolUseId"] for block in turns[2]["content"]] == ["t1", "t2"]


def test_user_text_is_not_merged_into_a_tool_result_turn(model: AwsBedrock):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="start"),
            *_tool_exchange("t1"),
            Message(role="user", content="and one more thing"),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "user"]
    assert _kinds(turns[2]) == ["toolResult"]
    assert turns[3]["content"] == [{"text": "and one more thing"}]


def test_user_messages_after_a_tool_result_turn_merge_with_each_other_only(model: AwsBedrock, image: Image):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="start"),
            *_tool_exchange("t1"),
            Message(role="user", content="note"),
            Message(role="user", images=[image]),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "user"]
    assert _kinds(turns[2]) == ["toolResult"]
    assert _kinds(turns[3]) == ["text", "image"]


def test_image_only_user_message_between_two_tool_results(model: AwsBedrock, image: Image):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="start"),
            *_tool_exchange("t1"),
            Message(role="user", images=[image]),
            *_tool_exchange("t2"),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "user", "assistant", "user"]
    assert _kinds(turns[2]) == ["toolResult"]
    assert _kinds(turns[3]) == ["image"]
    assert _kinds(turns[5]) == ["toolResult"]
    _assert_no_empty_text_block(turns)


def test_tool_result_after_user_text_is_a_turn_of_its_own(model: AwsBedrock):
    turns, _ = model._format_messages(
        [Message(role="user", content="text"), Message(role="tool", tool_call_id="t1", content="one")]
    )

    assert [_kinds(turn) for turn in turns] == [["text"], ["toolResult"]]


def test_merge_does_not_mutate_message_content(model: AwsBedrock, image: Image):
    first = Message(role="user", content=[{"text": "FIRST"}])
    second = Message(role="user", content=[{"text": "SECOND"}], images=[image])
    first_content, second_content = first.content, second.content

    model._format_messages([first, second])
    turns, _ = model._format_messages([first, second])

    assert _kinds(turns[0]) == ["text", "text", "image"]
    assert first.content is first_content and first.content == [{"text": "FIRST"}]
    assert second.content is second_content and second.content == [{"text": "SECOND"}]


def test_consecutive_assistant_messages_are_left_as_separate_turns(model: AwsBedrock):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="hi"),
            Message(role="assistant", content="one"),
            Message(role="assistant", content="two"),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "assistant"]


def test_trailing_user_rule_after_a_merge(image: Image):
    model = AwsBedrock(id="amazon.nova-lite-v1:0", append_trailing_user_message=True)

    ends_with_user, _ = model._format_messages(
        [Message(role="user", content="note"), Message(role="user", images=[image])]
    )
    ends_with_assistant, _ = model._format_messages(
        [
            Message(role="user", content="note"),
            Message(role="user", content="question"),
            Message(role="assistant", content="reply"),
        ]
    )

    assert [turn["role"] for turn in ends_with_user] == ["user"]
    assert [turn["role"] for turn in ends_with_assistant] == ["user", "assistant", "user"]
    assert ends_with_assistant[2]["content"] == [{"text": model.trailing_user_message_content}]


@pytest.mark.parametrize("content", [None, "", []])
def test_user_message_with_no_text_and_no_media_keeps_its_turn(model: AwsBedrock, content: Any):
    """A turn replayed from history after its media was removed has no content left."""
    turns, _ = model._format_messages(
        [
            Message(role="user", content=content),
            Message(role="assistant", content="It is a red square."),
            Message(role="user", content="What colour was it?"),
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == [{"text": "(no text)"}]
    assert turns[2]["content"] == [{"text": "What colour was it?"}]


def test_empty_user_message_next_to_a_user_message_adds_nothing(model: AwsBedrock):
    turns, _ = model._format_messages(
        [Message(role="user", content="Note: the order shipped."), Message(role="user", content=None)]
    )

    assert turns == [{"role": "user", "content": [{"text": "Note: the order shipped."}]}]


def test_empty_user_message_is_not_mutated(model: AwsBedrock):
    empty = Message(role="user", content=[])
    original = empty.content

    model._format_messages([empty])

    assert empty.content is original
    assert empty.content == []


def test_assistant_text_is_kept_beside_its_tool_calls(model: AwsBedrock):
    """A Converse response with text and a toolUse is stored as one message and must be replayed whole."""
    turns, _ = model._format_messages(
        [
            Message(role="user", content="Where is my order?"),
            Message(
                role="assistant",
                content="Let me look that up.",
                tool_calls=[{"id": "t1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
            ),
            Message(role="tool", tool_call_id="t1", content="shipped"),
        ]
    )

    assert _kinds(turns[1]) == ["text", "toolUse"]
    assert turns[1]["content"][0] == {"text": "Let me look that up."}


@pytest.mark.parametrize("content", [None, ""])
def test_assistant_tool_calls_without_text_have_no_text_block(model: AwsBedrock, content: Any):
    turns, _ = model._format_messages(
        [
            Message(role="user", content="Where is my order?"),
            Message(
                role="assistant",
                content=content,
                tool_calls=[{"id": "t1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
            ),
        ]
    )

    assert _kinds(turns[1]) == ["toolUse"]
