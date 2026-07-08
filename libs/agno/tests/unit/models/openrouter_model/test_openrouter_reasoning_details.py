"""Tests for merging streamed OpenRouter reasoning_details fragments.

Regression tests for https://github.com/agno-agi/agno/issues/8794: streamed
reasoning_details fragments were stored and replayed unmerged, which corrupts
Anthropic signed thinking blocks on the follow-up request of a tool loop.
"""

from agno.models.message import Message
from agno.models.openrouter import OpenRouter
from agno.models.openrouter.openrouter import _merge_streamed_reasoning_details


def test_fragments_with_same_index_are_merged():
    fragments = [
        {"type": "reasoning.text", "text": "Let", "format": "anthropic-claude-v1", "index": 0},
        {"type": "reasoning.text", "text": " me compute 17 * 23.", "format": "anthropic-claude-v1", "index": 0},
        {"type": "reasoning.text", "signature": "Et8BCmUIDxgC", "format": "anthropic-claude-v1", "index": 0},
    ]
    merged = _merge_streamed_reasoning_details(fragments)
    assert merged == [
        {
            "type": "reasoning.text",
            "text": "Let me compute 17 * 23.",
            "format": "anthropic-claude-v1",
            "index": 0,
            "signature": "Et8BCmUIDxgC",
        }
    ]


def test_multiple_indexes_produce_one_block_each_in_order():
    fragments = [
        {"type": "reasoning.text", "text": "first", "index": 0},
        {"type": "reasoning.text", "text": "second", "index": 1},
        {"type": "reasoning.text", "text": " block", "index": 0},
        {"type": "reasoning.text", "signature": "sig-1", "index": 1},
    ]
    merged = _merge_streamed_reasoning_details(fragments)
    assert merged == [
        {"type": "reasoning.text", "text": "first block", "index": 0},
        {"type": "reasoning.text", "text": "second", "signature": "sig-1", "index": 1},
    ]


def test_complete_blocks_without_index_pass_through_unchanged():
    blocks = [
        {"type": "reasoning.text", "text": "complete block", "signature": "sig"},
        {"type": "reasoning.encrypted", "data": "opaque"},
    ]
    assert _merge_streamed_reasoning_details(blocks) == blocks


def test_non_dict_entries_pass_through_unchanged():
    entries = ["not-a-dict", {"type": "reasoning.text", "text": "x", "index": 0}]
    merged = _merge_streamed_reasoning_details(entries)
    assert merged[0] == "not-a-dict"
    assert merged[1]["text"] == "x"


def test_last_signature_wins_and_none_values_ignored():
    fragments = [
        {"type": "reasoning.text", "text": "a", "signature": None, "index": 0},
        {"type": "reasoning.text", "text": None, "signature": "final-sig", "index": 0},
    ]
    merged = _merge_streamed_reasoning_details(fragments)
    assert merged == [{"type": "reasoning.text", "text": "a", "signature": "final-sig", "index": 0}]


def test_format_message_replays_merged_reasoning_details():
    model = OpenRouter(api_key="test-key")
    message = Message(
        role="assistant",
        content="391",
        provider_data={
            "reasoning_details": [
                {"type": "reasoning.text", "text": "Let", "format": "anthropic-claude-v1", "index": 0},
                {"type": "reasoning.text", "text": " me think.", "format": "anthropic-claude-v1", "index": 0},
                {"type": "reasoning.text", "signature": "sig", "format": "anthropic-claude-v1", "index": 0},
            ]
        },
    )
    message_dict = model._format_message(message)
    assert message_dict["reasoning_details"] == [
        {
            "type": "reasoning.text",
            "text": "Let me think.",
            "format": "anthropic-claude-v1",
            "index": 0,
            "signature": "sig",
        }
    ]


def test_format_message_does_not_mutate_stored_provider_data():
    model = OpenRouter(api_key="test-key")
    original = [
        {"type": "reasoning.text", "text": "a", "index": 0},
        {"type": "reasoning.text", "text": "b", "index": 0},
    ]
    message = Message(role="assistant", content="x", provider_data={"reasoning_details": original})
    model._format_message(message)
    assert message.provider_data["reasoning_details"] == [
        {"type": "reasoning.text", "text": "a", "index": 0},
        {"type": "reasoning.text", "text": "b", "index": 0},
    ]
