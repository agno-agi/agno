"""The same-role merge in format_messages must never mutate message content.

A list-shaped Message.content can be aliased into the chat payload, and the
message itself can be live session history. Merging consecutive same-role
messages must build a new content list; extending the existing one in place
corrupts the session message and compounds on every subsequent request.
"""

import pytest

pytest.importorskip("anthropic")

from agno.models.message import Message
from agno.utils.models.claude import format_messages


def test_merge_list_then_str_does_not_mutate_original():
    first = Message(role="user", content=[{"type": "text", "text": "FIRST"}])
    second = Message(role="user", content="SECOND")
    original_list = first.content

    chat_messages, _ = format_messages([first, second])

    assert chat_messages == [
        {"role": "user", "content": [{"type": "text", "text": "FIRST"}, {"type": "text", "text": "SECOND"}]}
    ]
    assert first.content is original_list
    assert original_list == [{"type": "text", "text": "FIRST"}]


def test_merge_str_then_list_does_not_mutate_original():
    first = Message(role="user", content="FIRST")
    second = Message(role="user", content=[{"type": "text", "text": "SECOND"}])
    original_list = second.content

    chat_messages, _ = format_messages([first, second])

    assert chat_messages == [
        {"role": "user", "content": [{"type": "text", "text": "FIRST"}, {"type": "text", "text": "SECOND"}]}
    ]
    assert second.content is original_list
    assert original_list == [{"type": "text", "text": "SECOND"}]


def test_merge_list_then_list_does_not_mutate_either():
    first = Message(role="user", content=[{"type": "text", "text": "FIRST"}])
    second = Message(role="user", content=[{"type": "text", "text": "SECOND"}])

    chat_messages, _ = format_messages([first, second])

    assert chat_messages == [
        {"role": "user", "content": [{"type": "text", "text": "FIRST"}, {"type": "text", "text": "SECOND"}]}
    ]
    assert first.content == [{"type": "text", "text": "FIRST"}]
    assert second.content == [{"type": "text", "text": "SECOND"}]


def test_repeated_formatting_is_stable():
    # The old in-place merge grew the first message's list on every call,
    # duplicating blocks on each subsequent request.
    first = Message(role="user", content=[{"type": "text", "text": "FIRST"}])
    second = Message(role="user", content=[{"type": "text", "text": "SECOND"}])

    for _ in range(3):
        chat_messages, _ = format_messages([first, second])
        assert chat_messages[0]["content"] == [
            {"type": "text", "text": "FIRST"},
            {"type": "text", "text": "SECOND"},
        ]
