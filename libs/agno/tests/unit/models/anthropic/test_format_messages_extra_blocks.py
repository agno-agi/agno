"""
Regression test for #7171 - format_messages() must preserve server-side tool
blocks in the conversation history.

When Claude uses code-execution skills (computer-use), the API response can
contain the following block types inside response.content:

  * server_tool_use
  * bash_code_execution_tool_result
  * text_editor_code_execution_tool_result

These blocks were previously discarded by _parse_provider_response() and never
stored on the Message object, so format_messages() had nothing to re-send in
subsequent turns.  Without them Claude has no memory of having executed code
and enters an infinite retry loop.

The fix stores raw serialised copies in
    message.provider_data["extra_content_blocks"]
and format_messages() reconstructs native Anthropic block objects from them.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.models.message import Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_server_tool_use_block(block_id: str = "srvtu_01", name: str = "bash_code_execution") -> dict:
    """Return a dict representation of a ServerToolUseBlock."""
    return {
        "type": "server_tool_use",
        "id": block_id,
        "name": name,
        "input": {},
        "caller": None,
    }


def _make_bash_result_block(tool_use_id: str = "srvtu_01") -> dict:
    """Return a dict representation of a BashCodeExecutionToolResultBlock."""
    return {
        "type": "bash_code_execution_tool_result",
        "tool_use_id": tool_use_id,
        "content": {"type": "bash_code_execution_output", "output": "Hello, world!\n", "stderr": ""},
    }


def _make_text_editor_result_block(tool_use_id: str = "srvtu_02") -> dict:
    """Return a dict representation of a TextEditorCodeExecutionToolResultBlock."""
    return {
        "type": "text_editor_code_execution_tool_result",
        "tool_use_id": tool_use_id,
        "content": {"type": "text_editor_code_execution_view_result", "output": "file content"},
    }


# ---------------------------------------------------------------------------
# Tests for _parse_provider_response – blocks must be stored in provider_data
# ---------------------------------------------------------------------------

class TestParseProviderResponseStoresExtraBlocks:
    """_parse_provider_response() must persist server-tool blocks into provider_data."""

    def _build_mock_response(self, extra_blocks: list):
        """Build a minimal mock Anthropic Message response."""
        response = MagicMock()
        response.role = "assistant"
        response.stop_reason = "end_turn"
        response.content = []
        response.usage = MagicMock()
        response.usage.input_tokens = 10
        response.usage.output_tokens = 5
        response.usage.cache_creation_input_tokens = 0
        response.usage.cache_read_input_tokens = 0
        response.usage.server_tool_use = None

        for raw in extra_blocks:
            block = MagicMock()
            block.type = raw["type"]
            if raw["type"] == "server_tool_use":
                block.id = raw["id"]
                block.name = raw["name"]
                block.input = raw["input"]
                block.caller = raw["caller"]
            else:
                block.tool_use_id = raw["tool_use_id"]
                block.content = raw["content"]
            block.model_dump.return_value = raw
            response.content.append(block)

        return response

    def test_server_tool_use_stored_in_provider_data(self):
        """server_tool_use block must appear in provider_data['extra_content_blocks']."""
        from agno.models.anthropic.claude import Claude

        model = Claude(id="claude-opus-4-5")
        raw = _make_server_tool_use_block()
        response = self._build_mock_response([raw])

        model_response = model._parse_provider_response(response)

        assert model_response.provider_data is not None, "provider_data must not be None"
        extra = model_response.provider_data.get("extra_content_blocks", [])
        assert len(extra) == 1
        assert extra[0]["type"] == "server_tool_use"
        assert extra[0]["id"] == raw["id"]

    def test_bash_code_execution_tool_result_stored_in_provider_data(self):
        """bash_code_execution_tool_result block must be stored."""
        from agno.models.anthropic.claude import Claude

        model = Claude(id="claude-opus-4-5")
        raw = _make_bash_result_block()
        response = self._build_mock_response([raw])

        model_response = model._parse_provider_response(response)

        assert model_response.provider_data is not None
        extra = model_response.provider_data.get("extra_content_blocks", [])
        assert len(extra) == 1
        assert extra[0]["type"] == "bash_code_execution_tool_result"

    def test_text_editor_code_execution_tool_result_stored_in_provider_data(self):
        """text_editor_code_execution_tool_result block must be stored."""
        from agno.models.anthropic.claude import Claude

        model = Claude(id="claude-opus-4-5")
        raw = _make_text_editor_result_block()
        response = self._build_mock_response([raw])

        model_response = model._parse_provider_response(response)

        assert model_response.provider_data is not None
        extra = model_response.provider_data.get("extra_content_blocks", [])
        assert len(extra) == 1
        assert extra[0]["type"] == "text_editor_code_execution_tool_result"

    def test_multiple_extra_blocks_all_stored(self):
        """All extra block types must be collected together."""
        from agno.models.anthropic.claude import Claude

        model = Claude(id="claude-opus-4-5")
        raws = [
            _make_server_tool_use_block("id1", "bash"),
            _make_bash_result_block("id1"),
            _make_text_editor_result_block("id2"),
        ]
        response = self._build_mock_response(raws)

        model_response = model._parse_provider_response(response)

        extra = (model_response.provider_data or {}).get("extra_content_blocks", [])
        assert len(extra) == 3
        types = [b["type"] for b in extra]
        assert "server_tool_use" in types
        assert "bash_code_execution_tool_result" in types
        assert "text_editor_code_execution_tool_result" in types


# ---------------------------------------------------------------------------
# Tests for format_messages – blocks must reappear in the chat history
# ---------------------------------------------------------------------------

class TestFormatMessagesPreservesExtraBlocks:
    """format_messages() must reconstruct extra blocks from provider_data."""

    def _assistant_message_with_extra_blocks(self, extra_blocks: list) -> Message:
        return Message(
            role="assistant",
            content="Running code…",
            provider_data={"extra_content_blocks": extra_blocks},
        )

    def _get_block_types(self, content: list) -> list:
        """Extract type field from a list of content blocks (dict or object)."""
        return [
            b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
            for b in content
        ]

    def test_server_tool_use_present_in_formatted_history(self):
        """server_tool_use block must appear in the formatted assistant content."""
        from agno.utils.models.claude import format_messages

        msg = self._assistant_message_with_extra_blocks([_make_server_tool_use_block()])
        chat_messages, _ = format_messages([msg])

        assert len(chat_messages) == 1
        block_types = self._get_block_types(chat_messages[0]["content"])
        assert "server_tool_use" in block_types, (
            "server_tool_use block must be preserved in message history"
        )

    def test_bash_code_execution_tool_result_present_in_formatted_history(self):
        """bash_code_execution_tool_result block must appear in formatted content."""
        from agno.utils.models.claude import format_messages

        msg = self._assistant_message_with_extra_blocks([_make_bash_result_block()])
        chat_messages, _ = format_messages([msg])

        assert len(chat_messages) == 1
        block_types = self._get_block_types(chat_messages[0]["content"])
        assert "bash_code_execution_tool_result" in block_types, (
            "bash_code_execution_tool_result block must be preserved in message history"
        )

    def test_text_editor_code_execution_tool_result_present_in_formatted_history(self):
        """text_editor_code_execution_tool_result block must appear in formatted content."""
        from agno.utils.models.claude import format_messages

        msg = self._assistant_message_with_extra_blocks([_make_text_editor_result_block()])
        chat_messages, _ = format_messages([msg])

        assert len(chat_messages) == 1
        block_types = self._get_block_types(chat_messages[0]["content"])
        assert "text_editor_code_execution_tool_result" in block_types, (
            "text_editor_code_execution_tool_result block must be preserved in message history"
        )

    def test_no_extra_blocks_when_provider_data_absent(self):
        """Messages without provider_data must not raise and must contain only text."""
        from agno.utils.models.claude import format_messages

        msg = Message(role="assistant", content="Hello!")
        chat_messages, _ = format_messages([msg])

        assert len(chat_messages) == 1
        block_types = self._get_block_types(chat_messages[0]["content"])
        assert block_types == ["text"]

    def test_all_extra_block_types_preserved_together(self):
        """All three extra block types must survive a round-trip through format_messages."""
        from agno.utils.models.claude import format_messages

        raws = [
            _make_server_tool_use_block("id1", "bash_code_execution"),
            _make_bash_result_block("id1"),
            _make_text_editor_result_block("id2"),
        ]
        msg = self._assistant_message_with_extra_blocks(raws)
        msg.content = "Executing…"
        chat_messages, _ = format_messages([msg])

        block_types = self._get_block_types(chat_messages[0]["content"])
        assert "server_tool_use" in block_types
        assert "bash_code_execution_tool_result" in block_types
        assert "text_editor_code_execution_tool_result" in block_types
