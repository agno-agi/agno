"""Tests for the Message class."""

import json

from agno.models.message import Message


class TestGetContentString:
    """Tests for Message.get_content_string() method."""

    def test_string_content(self):
        """Test that string content is returned as-is."""
        message = Message(role="assistant", content="Hello, world!")
        assert message.get_content_string() == "Hello, world!"

    def test_empty_list_content_returns_empty_string(self):
        """Test that empty list content returns empty string, not '[]'.

        This is a regression test for the bug where empty content lists
        (common after tool execution) would return '[]' string.
        """
        message = Message(role="assistant", content=[])
        result = message.get_content_string()
        assert result == ""
        assert result != "[]"

    def test_list_with_text_dict(self):
        """Test that list with text dict returns the text."""
        message = Message(role="assistant", content=[{"text": "Hello from list"}])
        assert message.get_content_string() == "Hello from list"

    def test_list_with_text_dict_empty_text(self):
        """Test that list with empty text returns empty string."""
        message = Message(role="assistant", content=[{"text": ""}])
        assert message.get_content_string() == ""

    def test_list_with_non_text_dict(self):
        """Test that list with non-text dict returns JSON."""
        content = [{"type": "image", "url": "http://example.com/image.png"}]
        message = Message(role="assistant", content=content)
        assert message.get_content_string() == json.dumps(content)

    def test_list_with_multiple_items(self):
        """Test that list with multiple items returns first text."""
        message = Message(
            role="assistant",
            content=[{"text": "First"}, {"text": "Second"}],
        )
        assert message.get_content_string() == "First"

    def test_none_content(self):
        """Test that None content returns empty string."""
        message = Message(role="assistant", content=None)
        assert message.get_content_string() == ""

    def test_list_with_strings(self):
        """Test that list of strings returns JSON dump."""
        content = ["item1", "item2"]
        message = Message(role="assistant", content=content)
        assert message.get_content_string() == json.dumps(content)


class TestGetContent:
    """Tests for Message.get_content() compressed-content fallback."""

    def test_none_compressed_content_returns_original(self):
        """None means compression has not been recorded; return original content."""
        message = Message(role="tool", content="original tool result")
        assert message.compressed_content is None
        assert message.get_content(use_compressed_content=True) == "original tool result"
        assert message.get_content(use_compressed_content=False) == "original tool result"

    def test_empty_compressed_content_falls_back_to_original(self):
        """Empty string is an already-attempted marker, not usable compressed content."""
        message = Message(role="tool", content="original tool result", compressed_content="")
        assert message.compressed_content == ""
        assert message.get_content(use_compressed_content=True) == "original tool result"
        assert message.get_content(use_compressed_content=False) == "original tool result"

    def test_non_empty_compressed_content_is_returned(self):
        """Successful compression is returned when requested."""
        message = Message(
            role="tool",
            content="original tool result",
            compressed_content="some compressed result",
        )
        assert message.get_content(use_compressed_content=True) == "some compressed result"
        assert message.get_content(use_compressed_content=False) == "original tool result"

    def test_empty_compressed_content_survives_to_dict_from_dict(self):
        """Empty-string marker must round-trip so compression is not retried after persist."""
        message = Message(role="tool", content="original tool result", compressed_content="")
        restored = Message.from_dict(message.to_dict())
        assert restored.compressed_content == ""
        assert restored.get_content(use_compressed_content=True) == "original tool result"
