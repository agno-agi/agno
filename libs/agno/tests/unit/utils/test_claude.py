import base64

import pytest

from agno.media import File
from agno.models.message import Message
from agno.utils.models.claude import _apply_cache_control, _format_file_for_message, format_messages


class TestFormatFileForMessage:
    def test_filepath_text_csv_returns_text_source(self, tmp_path):
        csv_content = "name,age\nAlice,30\nBob,25"
        p = tmp_path / "data.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == csv_content
        assert result["citations"] == {"enabled": True}

    def test_filepath_pdf_returns_base64_source(self, tmp_path):
        pdf_bytes = b"%PDF-1.4 fake content"
        p = tmp_path / "doc.pdf"
        p.write_bytes(pdf_bytes)

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(result["source"]["data"]) == pdf_bytes

    def test_bytes_content_text_mime_returns_text_source(self):
        raw = b"col1,col2\na,b"

        result = _format_file_for_message(File(content=raw, mime_type="text/csv"))

        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == "col1,col2\na,b"

    def test_bytes_content_pdf_returns_base64_source(self):
        raw = b"fake-pdf-bytes"

        result = _format_file_for_message(File(content=raw, mime_type="application/pdf"))

        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(result["source"]["data"]) == raw

    def test_filepath_no_mime_guesses_from_extension(self, tmp_path):
        p = tmp_path / "report.csv"
        p.write_text("x,y\n1,2")

        result = _format_file_for_message(File(filepath=str(p)))

        assert result["source"]["type"] == "text"
        assert result["source"]["data"] == "x,y\n1,2"

    def test_filepath_nonexistent_returns_none(self):
        result = _format_file_for_message(File(filepath="/nonexistent/file.pdf", mime_type="application/pdf"))

        assert result is None

    @pytest.mark.parametrize(
        "mime_type",
        ["text/plain", "text/html", "text/xml", "text/javascript", "application/json", "application/x-python"],
    )
    def test_all_text_mimes_route_to_text_source(self, mime_type):
        raw = b"some text content"

        result = _format_file_for_message(File(content=raw, mime_type=mime_type))

        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"

    def test_text_data_is_not_base64_encoded(self, tmp_path):
        """Regression: old code base64-encoded before checking MIME, sending gibberish as text."""
        csv_content = "name,value\ntest,123"
        p = tmp_path / "test.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["source"]["data"] == csv_content
        assert result["source"]["data"] != base64.standard_b64encode(csv_content.encode()).decode()


class TestFormatMessagesMultiBlockCache:
    """Tests for multi-block system message caching in format_messages()."""

    def test_no_cache_control_returns_string(self):
        """Without cache_control, returns concatenated string (backwards compatible)."""
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="system", content="Be concise."),
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, str)
        assert system_message == "You are helpful. Be concise."
        assert len(chat_messages) == 1
        assert chat_messages[0]["role"] == "user"

    def test_with_cache_control_returns_list(self):
        """With cache_control on any message, returns list of structured blocks."""
        messages = [
            Message(
                role="system",
                content="Static instructions",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="system", content="Dynamic context"),
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 2
        assert system_message[0]["type"] == "text"
        assert system_message[0]["text"] == "Static instructions"
        assert system_message[0]["cache_control"] == {"type": "ephemeral"}
        assert system_message[1]["type"] == "text"
        assert system_message[1]["text"] == "Dynamic context"
        assert "cache_control" not in system_message[1]

    def test_cache_control_with_extended_ttl(self):
        """Cache control with extended TTL is preserved."""
        messages = [
            Message(
                role="system",
                content="Instructions",
                provider_data={"cache_control": {"type": "ephemeral", "ttl": "1h"}},
            ),
        ]
        _, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert system_message[0]["cache_control"]["ttl"] == "1h"

    def test_developer_role_treated_as_system(self):
        """Developer role messages are treated as system messages."""
        messages = [
            Message(
                role="developer",
                content="Developer instructions",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="user", content="Hello"),
        ]
        _, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 1
        assert system_message[0]["text"] == "Developer instructions"

    def test_empty_system_messages_returns_empty_string(self):
        """No system messages returns empty string."""
        messages = [Message(role="user", content="Hello")]
        _, system_message = format_messages(messages)

        assert system_message == ""

    def test_provider_data_without_cache_control_returns_string(self):
        """provider_data without cache_control key returns string format."""
        messages = [
            Message(
                role="system",
                content="Instructions",
                provider_data={"other_key": "value"},
            ),
        ]
        _, system_message = format_messages(messages)

        assert isinstance(system_message, str)
        assert system_message == "Instructions"

    def test_multiple_cache_control_blocks(self):
        """Multiple blocks can have cache_control."""
        messages = [
            Message(
                role="system",
                content="Static A",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="system", content="Dynamic"),
            Message(
                role="system",
                content="Static B",
                provider_data={"cache_control": {"type": "ephemeral", "ttl": "1h"}},
            ),
            Message(role="user", content="Hello"),
        ]
        _, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 3
        assert system_message[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in system_message[1]
        assert system_message[2]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_system_messages_order_preserved(self):
        """System messages maintain their order in list format."""
        messages = [
            Message(
                role="system",
                content="First",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="system", content="Second"),
            Message(role="system", content="Third"),
            Message(role="user", content="Hello"),
        ]
        _, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert [b["text"] for b in system_message] == ["First", "Second", "Third"]

    def test_chat_messages_unaffected_by_cache_control(self):
        """User and assistant messages are unaffected by system cache_control."""
        messages = [
            Message(
                role="system",
                content="System",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="user", content="User question"),
            Message(role="assistant", content="Assistant response"),
            Message(role="user", content="Follow up"),
        ]
        chat_messages, _ = format_messages(messages)

        assert len(chat_messages) == 3
        assert chat_messages[0]["role"] == "user"
        assert chat_messages[1]["role"] == "assistant"
        assert chat_messages[2]["role"] == "user"


class TestApplyCacheControl:
    """Tests for _apply_cache_control helper."""

    def test_no_provider_data_returns_unchanged(self):
        msg = Message(role="user", content="hi")
        content = [{"type": "text", "text": "hi"}]
        result = _apply_cache_control(content, msg)
        assert result == content
        assert "cache_control" not in result[0]

    def test_empty_content_returns_unchanged(self):
        msg = Message(role="user", content="hi", provider_data={"cache_control": {"type": "ephemeral"}})
        result = _apply_cache_control([], msg)
        assert result == []

    def test_dict_block_gets_cache_control(self):
        msg = Message(role="user", content="hi", provider_data={"cache_control": {"type": "ephemeral"}})
        content = [{"type": "text", "text": "hi"}]
        result = _apply_cache_control(content, msg)
        assert result[-1]["cache_control"] == {"type": "ephemeral"}

    def test_only_last_block_gets_cache_control(self):
        msg = Message(role="user", content="hi", provider_data={"cache_control": {"type": "ephemeral"}})
        content = [
            {"type": "text", "text": "block1"},
            {"type": "text", "text": "block2"},
        ]
        result = _apply_cache_control(content, msg)
        assert "cache_control" not in result[0]
        assert result[1]["cache_control"] == {"type": "ephemeral"}

    def test_sdk_object_converted_to_dict(self):
        from anthropic.types import TextBlock

        msg = Message(role="assistant", content="hi", provider_data={"cache_control": {"type": "ephemeral"}})
        content = [TextBlock(text="hello", type="text")]
        result = _apply_cache_control(content, msg)
        assert isinstance(result[0], dict)
        assert result[0]["cache_control"] == {"type": "ephemeral"}
        assert result[0]["text"] == "hello"

    def test_provider_data_without_cache_control_key(self):
        msg = Message(role="user", content="hi", provider_data={"other": "data"})
        content = [{"type": "text", "text": "hi"}]
        result = _apply_cache_control(content, msg)
        assert "cache_control" not in result[0]


class TestNonSystemCacheControl:
    """Tests for cache_control on user, assistant, and tool messages in format_messages()."""

    def test_user_message_with_cache_control(self):
        messages = [
            Message(
                role="user",
                content="A long document to cache",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
        ]
        chat_messages, _ = format_messages(messages)

        assert len(chat_messages) == 1
        content = chat_messages[0]["content"]
        assert content[-1]["cache_control"] == {"type": "ephemeral"}

    def test_user_message_without_cache_control_unchanged(self):
        messages = [
            Message(role="user", content="Simple message"),
        ]
        chat_messages, _ = format_messages(messages)

        content = chat_messages[0]["content"]
        assert "cache_control" not in content[-1]

    def test_tool_message_with_cache_control(self):
        messages = [
            Message(
                role="tool",
                content="Large tool result",
                tool_call_id="call_123",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
        ]
        chat_messages, _ = format_messages(messages)

        assert len(chat_messages) == 1
        content = chat_messages[0]["content"]
        assert content[-1]["cache_control"] == {"type": "ephemeral"}
        assert content[-1]["type"] == "tool_result"

    def test_assistant_message_with_cache_control_converts_sdk_objects(self):
        messages = [
            Message(
                role="assistant",
                content="Hello there",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
        ]
        chat_messages, _ = format_messages(messages)

        assert len(chat_messages) == 1
        content = chat_messages[0]["content"]
        # The TextBlock should have been converted to a dict
        assert isinstance(content[-1], dict)
        assert content[-1]["cache_control"] == {"type": "ephemeral"}
        assert content[-1]["text"] == "Hello there"

    def test_assistant_with_tool_calls_cache_on_last_block(self):
        import json

        messages = [
            Message(
                role="assistant",
                content="Let me search",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": json.dumps({"q": "test"})},
                    }
                ],
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
        ]
        chat_messages, _ = format_messages(messages)

        content = chat_messages[0]["content"]
        # Last block is the tool_use, should have cache_control
        assert isinstance(content[-1], dict)
        assert content[-1]["cache_control"] == {"type": "ephemeral"}
        assert content[-1]["type"] == "tool_use"
        # Earlier blocks should not have cache_control
        for block in content[:-1]:
            block_dict = (
                block if isinstance(block, dict) else block.model_dump() if hasattr(block, "model_dump") else block
            )
            assert "cache_control" not in block_dict

    def test_mixed_system_and_user_cache_control(self):
        messages = [
            Message(
                role="system",
                content="System instructions",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(
                role="user",
                content="Cached user input",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
        ]
        chat_messages, system_message = format_messages(messages)

        # System message should be structured blocks
        assert isinstance(system_message, list)
        assert system_message[0]["cache_control"] == {"type": "ephemeral"}

        # User message should also have cache_control
        assert len(chat_messages) == 1
        content = chat_messages[0]["content"]
        assert content[-1]["cache_control"] == {"type": "ephemeral"}
