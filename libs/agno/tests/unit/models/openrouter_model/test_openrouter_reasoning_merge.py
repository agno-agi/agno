"""Tests for OpenRouter streamed reasoning_details fragment merging (#8794).

OpenRouter streams one reasoning block across multiple chunks with the same
``index``; text arrives in pieces and the signature can arrive in a final
text-less fragment. Agno's streaming accumulator ``extend``s each fragment into a
list, so the stored ``reasoning_details`` becomes separate partial fragments
instead of one complete signed block per index. Replaying those fragments
verbatim makes Anthropic reject the next request with an invalid ``signature``
in the ``thinking`` block.

These tests verify the OpenRouter model reconstructs one complete reasoning
detail object per ``index`` (concatenated text + carried signature) before
replay, while leaving other provider-data lists (e.g. server_tool_blocks) and
Gemini-style encrypted entries with distinct indexes untouched.
"""

from agno.models.message import Message
from agno.models.openrouter.openrouter import OpenRouter, _merge_reasoning_details


def test_merges_text_fragments_and_carries_signature_for_one_index():
    """The issue's streaming shape: 3 fragments for index 0 -> 1 complete block."""
    fragments = [
        {"type": "reasoning.text", "text": "Let", "format": "anthropic-claude-v1", "index": 0},
        {"type": "reasoning.text", "text": " me compute 17 * 23.", "format": "anthropic-claude-v1", "index": 0},
        {"type": "reasoning.text", "signature": "Et8BCmUIDxgC...", "format": "anthropic-claude-v1", "index": 0},
    ]

    merged = _merge_reasoning_details(fragments)

    assert merged == [
        {
            "type": "reasoning.text",
            "text": "Let me compute 17 * 23.",
            "signature": "Et8BCmUIDxgC...",
            "format": "anthropic-claude-v1",
            "index": 0,
        }
    ]


def test_separate_indexes_remain_separate_blocks():
    """Distinct indexes produce distinct merged blocks (Gemini encrypted entries)."""
    fragments = [
        {"type": "reasoning.encrypted", "data": "AAA", "index": 0},
        {"type": "reasoning.encrypted", "data": "BBB", "index": 1},
    ]

    merged = _merge_reasoning_details(fragments)

    assert len(merged) == 2
    assert merged[0]["data"] == "AAA"
    assert merged[0]["index"] == 0
    assert merged[1]["data"] == "BBB"
    assert merged[1]["index"] == 1


def test_concatenates_text_in_arrival_order():
    fragments = [
        {"type": "reasoning.text", "text": "a", "index": 0},
        {"type": "reasoning.text", "text": "b", "index": 0},
        {"type": "reasoning.text", "text": "c", "index": 0},
    ]
    merged = _merge_reasoning_details(fragments)
    assert merged[0]["text"] == "abc"


def test_carries_structural_fields_type_format_id():
    """Non-text structural fields are carried onto the merged block."""
    fragments = [
        {"type": "reasoning.text", "text": "hello", "format": "anthropic-claude-v1", "index": 0},
        {"type": "reasoning.text", "id": "r-123", "index": 0},
    ]
    merged = _merge_reasoning_details(fragments)
    assert merged[0]["type"] == "reasoning.text"
    assert merged[0]["format"] == "anthropic-claude-v1"
    assert merged[0]["id"] == "r-123"
    assert merged[0]["text"] == "hello"


def test_fragment_without_index_is_preserved():
    """A fragment that lacks an index is passed through unchanged (cannot group)."""
    fragments = [{"type": "reasoning.text", "text": "lonely"}]
    merged = _merge_reasoning_details(fragments)
    assert merged == [{"type": "reasoning.text", "text": "lonely"}]


def test_none_or_empty_returns_empty():
    assert _merge_reasoning_details(None) == []
    assert _merge_reasoning_details([]) == []


def test_non_dict_entries_pass_through():
    """Malformed (non-dict) entries are preserved as-is rather than crashing."""
    fragments = [{"type": "reasoning.text", "text": "ok", "index": 0}, "garbage"]  # type: ignore[list-item]
    merged = _merge_reasoning_details(fragments)
    # The dict is grouped; the stray string is preserved unchanged.
    assert any(isinstance(m, dict) and m.get("text") == "ok" for m in merged)
    assert "garbage" in merged


def test_format_message_replays_merged_reasoning_details():
    """_format_message must reconstruct complete blocks before emitting for replay."""
    model = OpenRouter(api_key="test-key")
    # The stored assistant message holds the streamed FRAGMENTS (the broken shape).
    message = Message(
        role="assistant",
        content="42",
        provider_data={
            "reasoning_details": [
                {"type": "reasoning.text", "text": "Let", "format": "anthropic-claude-v1", "index": 0},
                {"type": "reasoning.text", "text": " me compute.", "format": "anthropic-claude-v1", "index": 0},
                {"type": "reasoning.text", "signature": "sig", "format": "anthropic-claude-v1", "index": 0},
            ]
        },
    )

    formatted = model._format_message(message)

    rd = formatted["reasoning_details"]
    # Exactly ONE complete block per index — no partial fragments.
    assert len(rd) == 1
    assert rd[0]["text"] == "Let me compute."
    assert rd[0]["signature"] == "sig"


def test_format_message_leaves_other_provider_data_lists_untouched():
    """server_tool_blocks and other provider-data keys must not be altered.

    The base _format_message only carries explicitly-mapped provider-data keys
    (OpenRouter maps reasoning_details); the stored message's provider_data is
    never mutated by the merge.
    """
    model = OpenRouter(api_key="test-key")
    message = Message(
        role="assistant",
        content="ok",
        provider_data={
            "server_tool_blocks": [{"type": "tool_use", "id": "t1"}],
        },
    )

    formatted = model._format_message(message)

    # No reasoning_details key is added (there were none to merge).
    assert "reasoning_details" not in formatted
    # The stored message's other provider-data list is untouched.
    assert message.provider_data["server_tool_blocks"] == [{"type": "tool_use", "id": "t1"}]
