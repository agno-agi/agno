"""
Unit tests for Claude model prompt caching functionality.

Tests the enhanced caching features including:
- System message caching
- Tool definition caching
- Message content caching
- Cache control generation
- Usage metrics parsing
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.models.anthropic.claude import Claude
from agno.models.message import Message


class TestClaudePromptCaching:
    """Test Claude prompt caching functionality."""

    def test_cache_control_creation_default(self):
        """Test default cache_control creation."""
        claude = Claude()
        cache_control = claude._create_cache_control()

        assert cache_control == {"type": "ephemeral"}

    def test_cache_control_creation_1h_ttl(self):
        """Test cache_control creation with 1-hour TTL."""
        claude = Claude(cache_ttl="1h")
        cache_control = claude._create_cache_control()

        assert cache_control == {"type": "ephemeral", "ttl": "1h"}

    def test_cache_control_creation_extended_cache_time(self):
        """Test cache_control creation with extended_cache_time flag."""
        claude = Claude(extended_cache_time=True)
        cache_control = claude._create_cache_control()

        assert cache_control == {"type": "ephemeral", "ttl": "1h"}

    def test_cache_control_custom_ttl(self):
        """Test cache_control creation with custom TTL parameter."""
        claude = Claude()
        cache_control = claude._create_cache_control(ttl="1h")

        assert cache_control == {"type": "ephemeral", "ttl": "1h"}

    def test_system_message_caching_enabled(self):
        """Test system message preparation with caching enabled."""
        claude = Claude(cache_system_prompt=True)

        system_message = "You are a helpful assistant."
        kwargs = claude._prepare_request_kwargs(system_message)

        expected_system = [{"text": system_message, "type": "text", "cache_control": {"type": "ephemeral"}}]
        assert kwargs["system"] == expected_system

    def test_system_message_caching_disabled(self):
        """Test system message preparation with caching disabled."""
        claude = Claude(cache_system_prompt=False)

        system_message = "You are a helpful assistant."
        kwargs = claude._prepare_request_kwargs(system_message)

        expected_system = [{"text": system_message, "type": "text"}]
        assert kwargs["system"] == expected_system

    def test_enable_prompt_caching_flag(self):
        """Test that enable_prompt_caching enables system caching."""
        claude = Claude(enable_prompt_caching=True)

        system_message = "You are a helpful assistant."
        kwargs = claude._prepare_request_kwargs(system_message)

        assert "cache_control" in kwargs["system"][0]

    def test_tool_caching_enabled(self):
        """Test tool definition caching."""
        claude = Claude(cache_tool_definitions=True)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "A test tool",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string", "description": "Search query"}},
                        "required": ["query"],
                    },
                },
            }
        ]

        kwargs = claude._prepare_request_kwargs("system", tools)

        # Check that cache_control was added to the last tool
        assert "cache_control" in kwargs["tools"][-1]
        assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_tool_caching_disabled(self):
        """Test tool definition without caching."""
        claude = Claude(cache_tool_definitions=False)

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "A test tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        kwargs = claude._prepare_request_kwargs("system", tools)

        # Check that no cache_control was added
        assert "cache_control" not in kwargs["tools"][0]

    def test_message_caching_indices(self):
        """Test message caching with specific indices."""
        claude = Claude(cache_messages={"indices": [0, 2], "ttl": "5m"})

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Third message"},
        ]

        cached_messages = claude._apply_message_caching(messages)

        # Check that messages at indices 0 and 2 have cache_control
        assert cached_messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert cached_messages[2]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # Message at index 1 should not have cache_control
        assert isinstance(cached_messages[1]["content"], str)

    def test_message_caching_last_message(self):
        """Test caching the last message in conversation."""
        claude = Claude(cache_messages={"cache_last": True, "ttl": "1h"})

        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Last message"},
        ]

        cached_messages = claude._apply_message_caching(messages)

        # Only the last message should have cache_control
        assert isinstance(cached_messages[0]["content"], str)
        assert isinstance(cached_messages[1]["content"], str)
        assert cached_messages[2]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_message_caching_structured_content(self):
        """Test message caching with already structured content."""
        claude = Claude(cache_messages={"indices": [0]})

        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Structured message"}, {"type": "text", "text": "Second block"}],
            }
        ]

        cached_messages = claude._apply_message_caching(messages)

        # Cache control should be added to the last content block
        assert "cache_control" not in cached_messages[0]["content"][0]
        assert cached_messages[0]["content"][1]["cache_control"] == {"type": "ephemeral"}

    def test_beta_header_added_for_1h_cache(self):
        """Test that beta header is added for 1-hour cache."""
        claude = Claude(cache_ttl="1h")

        client_params = claude._get_client_params()

        assert "default_headers" in client_params
        assert client_params["default_headers"]["anthropic-beta"] == "extended-cache-ttl-2025-04-11"

    def test_beta_header_added_for_extended_cache_time(self):
        """Test that beta header is added when extended_cache_time is True."""
        claude = Claude(extended_cache_time=True)

        client_params = claude._get_client_params()

        assert "default_headers" in client_params
        assert client_params["default_headers"]["anthropic-beta"] == "extended-cache-ttl-2025-04-11"

    def test_beta_header_not_added_for_5m_cache(self):
        """Test that beta header is not added for default 5-minute cache."""
        claude = Claude(cache_ttl="5m")

        # Mock API key to avoid error
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            client_params = claude._get_client_params()

        # Should not add beta header for 5m cache
        if "default_headers" in client_params:
            assert "anthropic-beta" not in client_params.get("default_headers", {})

    def test_usage_metrics_parsing_basic(self):
        """Test parsing basic usage metrics."""
        claude = Claude()

        # Mock response with basic usage
        mock_response = Mock()
        mock_response.role = "assistant"
        mock_response.content = [Mock(type="text", text="Test response", citations=None)]
        mock_response.stop_reason = None

        # Create a mock usage object with only basic attributes
        mock_usage = Mock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_creation_input_tokens = 80
        mock_usage.cache_read_input_tokens = 20
        # Ensure cache_creation doesn't exist for this test
        del mock_usage.cache_creation
        mock_response.usage = mock_usage

        model_response = claude.parse_provider_response(mock_response)

        expected_usage = {"input_tokens": 100, "output_tokens": 50, "cache_write_tokens": 80, "cached_tokens": 20}
        assert model_response.response_usage == expected_usage

    def test_usage_metrics_parsing_enhanced(self):
        """Test parsing enhanced cache metrics for 1-hour cache."""
        claude = Claude()

        # Mock response with enhanced cache metrics
        mock_response = Mock()
        mock_response.role = "assistant"
        mock_response.content = [Mock(type="text", text="Test response", citations=None)]
        mock_response.stop_reason = None

        mock_cache_creation = Mock()
        mock_cache_creation.ephemeral_5m_input_tokens = 30
        mock_cache_creation.ephemeral_1h_input_tokens = 50

        mock_usage = Mock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_creation_input_tokens = 80
        mock_usage.cache_read_input_tokens = 20
        mock_usage.cache_creation = mock_cache_creation
        mock_response.usage = mock_usage

        model_response = claude.parse_provider_response(mock_response)

        expected_usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_write_tokens": 80,
            "cached_tokens": 20,
            "cache_5m_write_tokens": 30,
            "cache_1h_write_tokens": 50,
        }
        assert model_response.response_usage == expected_usage

    def test_usage_metrics_parsing_no_cache(self):
        """Test parsing usage metrics when no caching occurred."""
        claude = Claude()

        # Mock response without cache metrics
        mock_response = Mock()
        mock_response.role = "assistant"
        mock_response.content = [Mock(type="text", text="Test response", citations=None)]
        mock_response.stop_reason = None

        mock_usage = Mock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_creation_input_tokens = None
        mock_usage.cache_read_input_tokens = None
        # Ensure cache_creation doesn't exist for this test
        del mock_usage.cache_creation
        mock_response.usage = mock_usage

        model_response = claude.parse_provider_response(mock_response)

        expected_usage = {"input_tokens": 100, "output_tokens": 50}
        assert model_response.response_usage == expected_usage

    def test_comprehensive_caching_configuration(self):
        """Test a comprehensive caching configuration."""
        claude = Claude(
            enable_prompt_caching=True,
            cache_system_prompt=True,
            cache_tool_definitions=True,
            cache_messages={"cache_last": True, "ttl": "1h"},
            cache_ttl="1h",
        )

        system_message = "You are a helpful assistant."
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        kwargs = claude._prepare_request_kwargs(system_message, tools)

        # System message should be cached
        assert "cache_control" in kwargs["system"][0]
        assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

        # Tools should be cached
        assert "cache_control" in kwargs["tools"][-1]
        assert kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_empty_message_list_handling(self):
        """Test handling of empty message list for caching."""
        claude = Claude(cache_messages={"cache_last": True})

        empty_messages = []
        cached_messages = claude._apply_message_caching(empty_messages)

        assert cached_messages == []

    def test_no_cache_messages_config(self):
        """Test when cache_messages is None."""
        claude = Claude(cache_messages=None)

        messages = [{"role": "user", "content": "Test message"}]
        cached_messages = claude._apply_message_caching(messages)

        # Should return original messages unchanged
        assert cached_messages == messages


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__])
