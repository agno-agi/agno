"""
Tests for stripping output-only fields from Claude server-tool result blocks.

Anthropic *emits* a ``citations`` field on ``code_execution_tool_result`` blocks but
*rejects* it on input. agno preserves server-tool blocks in
``provider_data["server_tool_blocks"]`` for conversation-history reconstruction and
replays them verbatim on the next turn, which triggers a 400:

    messages.N.content.M.code_execution_tool_result.citations: Extra inputs are not permitted

The block is sanitized both when captured (``dump_server_tool_block``) and when replayed
(``format_messages``), so new and already-persisted history both stay valid.
"""

from agno.models.message import Message
from agno.utils.models.claude import (
    _strip_input_disallowed_block_fields,
    dump_server_tool_block,
    format_messages,
)


class _FakeBlock:
    """Stand-in for an Anthropic SDK content block exposing ``model_dump()``."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self) -> dict:
        return dict(self._data)


class TestDumpServerToolBlock:
    def test_strips_citations_from_code_execution_result(self):
        block = _FakeBlock(
            {"type": "code_execution_tool_result", "tool_use_id": "srvtoolu_1", "content": {}, "citations": None}
        )
        dumped = dump_server_tool_block(block)
        assert "citations" not in dumped
        assert dumped["type"] == "code_execution_tool_result"

    def test_strips_populated_citations_from_bash_code_execution_result(self):
        block = _FakeBlock(
            {
                "type": "bash_code_execution_tool_result",
                "tool_use_id": "srvtoolu_2",
                "content": {},
                "citations": [{"type": "char_location", "cited_text": "x"}],
            }
        )
        assert "citations" not in dump_server_tool_block(block)

    def test_preserves_unrelated_blocks(self):
        block = _FakeBlock({"type": "web_search_tool_result", "tool_use_id": "srvtoolu_3", "content": []})
        dumped = dump_server_tool_block(block)
        assert dumped == {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_3", "content": []}

    def test_strip_helper_is_idempotent(self):
        block = {"type": "code_execution_tool_result", "tool_use_id": "srvtoolu_4", "content": {}, "citations": []}
        _strip_input_disallowed_block_fields(block)
        _strip_input_disallowed_block_fields(block)
        assert "citations" not in block


class TestFormatMessagesReplayStripsCitations:
    def _assistant_with_stored_block(self) -> Message:
        # Simulates history persisted before the capture-time fix existed: the stored
        # server_tool_block still carries the output-only ``citations`` field.
        msg = Message(role="assistant", content="Here is the result.")
        msg.provider_data = {
            "server_tool_blocks": [
                {
                    "type": "code_execution_tool_result",
                    "tool_use_id": "srvtoolu_9",
                    "content": {"type": "code_execution_result", "stdout": "42\n"},
                    "citations": None,
                }
            ]
        }
        return msg

    def test_replayed_code_execution_block_omits_citations(self):
        chat_messages, _ = format_messages([self._assistant_with_stored_block()])
        result_blocks = [
            b
            for m in chat_messages
            for b in (m["content"] if isinstance(m["content"], list) else [])
            if isinstance(b, dict) and b.get("type") == "code_execution_tool_result"
        ]
        assert result_blocks, "code_execution_tool_result block missing from replayed payload"
        for block in result_blocks:
            assert "citations" not in block, (
                "citations must be stripped when replaying server-tool blocks — "
                "Anthropic rejects it on input with a 400"
            )
