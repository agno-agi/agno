"""
Unit tests for Claude utility functions.

Tests multi-block system message caching functionality.
"""

from agno.models.message import Message
from agno.utils.models.claude import format_messages


class TestFormatMessagesWithCacheControl:
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

        # First block has cache_control
        assert system_message[0]["type"] == "text"
        assert system_message[0]["text"] == "Static instructions"
        assert system_message[0]["cache_control"] == {"type": "ephemeral"}

        # Second block has no cache_control
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
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert system_message[0]["cache_control"]["type"] == "ephemeral"
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
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 1
        assert system_message[0]["text"] == "Developer instructions"

    def test_empty_system_messages_returns_empty_string(self):
        """No system messages returns empty string."""
        messages = [
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert system_message == ""

    def test_mixed_system_and_developer_with_cache_control(self):
        """Mixed system and developer roles with cache_control."""
        messages = [
            Message(
                role="system",
                content="System instructions",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="developer", content="Developer context"),
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 2
        assert system_message[0]["text"] == "System instructions"
        assert "cache_control" in system_message[0]
        assert system_message[1]["text"] == "Developer context"
        assert "cache_control" not in system_message[1]

    def test_provider_data_without_cache_control_returns_string(self):
        """provider_data without cache_control key returns string format."""
        messages = [
            Message(
                role="system",
                content="Instructions",
                provider_data={"other_key": "value"},
            ),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, str)
        assert system_message == "Instructions"

    def test_cache_control_on_last_message_only(self):
        """Cache control on last system message triggers list format for all."""
        messages = [
            Message(role="system", content="First"),
            Message(role="system", content="Second"),
            Message(
                role="system",
                content="Third with cache",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 3
        # First two have no cache_control
        assert "cache_control" not in system_message[0]
        assert "cache_control" not in system_message[1]
        # Third has cache_control
        assert system_message[2]["cache_control"] == {"type": "ephemeral"}

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
        chat_messages, system_message = format_messages(messages)

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
        chat_messages, system_message = format_messages(messages)

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
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(chat_messages) == 3
        assert chat_messages[0]["role"] == "user"
        assert chat_messages[1]["role"] == "assistant"
        assert chat_messages[2]["role"] == "user"

    def test_single_system_message_without_cache_control(self):
        """Single system message without cache_control returns string."""
        messages = [
            Message(role="system", content="Single instruction"),
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, str)
        assert system_message == "Single instruction"

    def test_single_system_message_with_cache_control(self):
        """Single system message with cache_control returns list."""
        messages = [
            Message(
                role="system",
                content="Single instruction",
                provider_data={"cache_control": {"type": "ephemeral"}},
            ),
            Message(role="user", content="Hello"),
        ]
        chat_messages, system_message = format_messages(messages)

        assert isinstance(system_message, list)
        assert len(system_message) == 1
        assert system_message[0]["text"] == "Single instruction"
        assert system_message[0]["cache_control"] == {"type": "ephemeral"}
