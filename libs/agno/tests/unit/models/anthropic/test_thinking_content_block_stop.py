"""
Unit tests for ContentBlockStopEvent thinking content handling in Claude model
"""

from unittest.mock import Mock

from anthropic.types import ContentBlockStopEvent

from agno.models.anthropic.claude import Claude
from agno.models.message import Message


class TestClaudeThinkingContentBlockStop:
    """Test Claude's handling of thinking content in ContentBlockStopEvent"""

    def test_content_block_stop_event_with_thinking(self):
        """Test that ContentBlockStopEvent with thinking content is properly parsed"""
        claude = Claude()

        # Mock ContentBlockStopEvent with thinking content
        stop_event = Mock(spec=ContentBlockStopEvent)
        stop_event.content_block = Mock()
        stop_event.content_block.type = "thinking"
        stop_event.content_block.thinking = "This is my complete thinking response."
        stop_event.content_block.signature = "thinking_signature_123"

        # Parse the event
        response = claude.parse_provider_response_delta(stop_event)

        # Verify thinking content is captured
        assert response.thinking == "This is my complete thinking response."
        assert response.provider_data is not None
        assert response.provider_data["signature"] == "thinking_signature_123"

    def test_content_block_stop_event_thinking_without_signature(self):
        """Test that ContentBlockStopEvent with thinking content works without signature"""
        claude = Claude()

        # Mock ContentBlockStopEvent with thinking content but no signature
        stop_event = Mock(spec=ContentBlockStopEvent)
        stop_event.content_block = Mock()
        stop_event.content_block.type = "thinking"
        stop_event.content_block.thinking = "Another thinking response."
        # Explicitly remove signature attribute to test the hasattr check
        del stop_event.content_block.signature

        # Parse the event
        response = claude.parse_provider_response_delta(stop_event)

        # Verify thinking content is captured
        assert response.thinking == "Another thinking response."
        assert response.provider_data is None  # Should be None when no signature

    def test_content_block_stop_event_tool_use_still_works(self):
        """Test that existing tool_use handling still works after adding thinking support"""
        claude = Claude()

        # Mock ContentBlockStopEvent with tool_use content (existing functionality)
        stop_event = Mock(spec=ContentBlockStopEvent)
        stop_event.content_block = Mock()
        stop_event.content_block.type = "tool_use"
        stop_event.content_block.id = "tool_123"
        stop_event.content_block.name = "search_web"
        stop_event.content_block.input = {"query": "test query"}

        # Parse the event
        response = claude.parse_provider_response_delta(stop_event)

        # Verify tool call is captured (existing functionality)
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0]["id"] == "tool_123"
        assert response.tool_calls[0]["function"]["name"] == "search_web"

    def test_content_block_stop_event_unknown_type(self):
        """Test that unknown content block types don't break the parser"""
        claude = Claude()

        # Mock ContentBlockStopEvent with unknown content type
        stop_event = Mock(spec=ContentBlockStopEvent)
        stop_event.content_block = Mock()
        stop_event.content_block.type = "unknown_type"

        # Parse the event - should not raise an exception
        response = claude.parse_provider_response_delta(stop_event)

        # Should return empty response without errors
        assert response.thinking is None
        assert response.provider_data is None
        assert len(response.tool_calls) == 0

    def test_thinking_content_in_message_serialization(self):
        """Test that thinking content is properly serialized in Message objects"""
        # Create a message with thinking content and signature
        message = Message(
            role="assistant",
            content="The answer is 42.",
            thinking="I need to think about the meaning of life. After careful consideration, 42 seems right.",
            provider_data={"signature": "thinking_sig_xyz789"},
        )

        # Serialize to dict
        message_dict = message.to_dict()

        # Verify thinking content is in the serialized data
        assert "thinking" in message_dict
        assert (
            message_dict["thinking"]
            == "I need to think about the meaning of life. After careful consideration, 42 seems right."
        )

        # Verify provider data is preserved
        assert "provider_data" in message_dict
        assert message_dict["provider_data"]["signature"] == "thinking_sig_xyz789"

    def test_multiple_thinking_events_processing(self):
        """Test processing multiple thinking ContentBlockStopEvent instances"""
        claude = Claude()

        thinking_contents = [
            ("First, let me understand the problem...", "sig_1"),
            ("Now I'll analyze the data...", "sig_2"),
            ("Finally, I can conclude...", "sig_3"),
        ]

        for thinking_text, signature in thinking_contents:
            # Create mock event
            stop_event = Mock(spec=ContentBlockStopEvent)
            stop_event.content_block = Mock()
            stop_event.content_block.type = "thinking"
            stop_event.content_block.thinking = thinking_text
            stop_event.content_block.signature = signature

            # Parse the event
            response = claude.parse_provider_response_delta(stop_event)

            # Verify each thinking block is captured correctly
            assert response.thinking == thinking_text
            assert response.provider_data["signature"] == signature
