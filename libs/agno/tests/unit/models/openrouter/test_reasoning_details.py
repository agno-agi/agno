"""
Tests for OpenRouter reasoning_details preservation.

Verifies that reasoning data is properly extracted from API responses and
included in subsequent requests. This is required for Gemini reasoning models
to preserve thought signatures across multi-turn tool calling.

Reference: https://openrouter.ai/docs/use-cases/reasoning-tokens
"""

from unittest.mock import MagicMock

import pytest

from agno.models.message import Message
from agno.models.openrouter import OpenRouter


class TestOpenRouterReasoningDetailsExtraction:
    """Test extraction of reasoning_details from API responses."""

    def test_extracts_reasoning_details_from_direct_attribute(self):
        """Test extraction when reasoning_details is a direct attribute."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        # Mock response with reasoning_details as direct attribute
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.tool_calls = None
        mock_message.function_call = None
        mock_message.reasoning_details = [{"type": "reasoning.text", "text": "thinking..."}]

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.id = "test-id"
        mock_response.error = None  # Required to prevent parent class error check

        result = model._parse_provider_response(mock_response)

        assert result.provider_data is not None
        assert "reasoning_details" in result.provider_data
        assert result.provider_data["reasoning_details"] == [{"type": "reasoning.text", "text": "thinking..."}]

    def test_extracts_reasoning_details_from_model_extra(self):
        """Test extraction when reasoning_details is in model_extra."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        # Mock response with reasoning_details in model_extra
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.tool_calls = None
        mock_message.function_call = None
        mock_message.reasoning_details = None
        mock_message.model_extra = {"reasoning_details": [{"type": "reasoning.encrypted", "data": "..."}]}

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.id = "test-id"
        mock_response.error = None

        result = model._parse_provider_response(mock_response)

        assert result.provider_data is not None
        assert "reasoning_details" in result.provider_data
        assert result.provider_data["reasoning_details"] == [{"type": "reasoning.encrypted", "data": "..."}]

    def test_extracts_reasoning_from_model_extra_fallback(self):
        """Test extraction when reasoning (not reasoning_details) is in model_extra."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        # Mock response with reasoning in model_extra (fallback field name)
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.tool_calls = None
        mock_message.function_call = None
        mock_message.reasoning_details = None
        mock_message.model_extra = {"reasoning": "Model's internal reasoning process"}

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.id = "test-id"
        mock_response.error = None

        result = model._parse_provider_response(mock_response)

        assert result.provider_data is not None
        assert "reasoning_details" in result.provider_data
        assert result.provider_data["reasoning_details"] == "Model's internal reasoning process"

    def test_no_reasoning_details_when_none_present(self):
        """Test that provider_data doesn't contain reasoning_details when not present."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        # Mock response without any reasoning data
        mock_message = MagicMock()
        mock_message.content = "Test response"
        mock_message.tool_calls = None
        mock_message.function_call = None
        mock_message.reasoning_details = None
        mock_message.model_extra = {}

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.id = "test-id"
        mock_response.error = None

        result = model._parse_provider_response(mock_response)

        # provider_data may or may not be set, but shouldn't have reasoning_details
        if result.provider_data:
            assert "reasoning_details" not in result.provider_data or result.provider_data.get("reasoning_details") is None


class TestOpenRouterReasoningDetailsFormatting:
    """Test that reasoning_details is included in formatted messages."""

    def test_includes_reasoning_details_in_assistant_message(self):
        """Test that reasoning_details is included when formatting assistant messages."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        message = Message(
            role="assistant",
            content="I'll help you with that.",
            provider_data={"reasoning_details": [{"type": "reasoning.text", "text": "thinking..."}]},
        )

        result = model._format_message(message)

        assert "reasoning_details" in result
        assert result["reasoning_details"] == [{"type": "reasoning.text", "text": "thinking..."}]

    def test_no_reasoning_details_for_user_message(self):
        """Test that reasoning_details is not added to user messages."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        message = Message(
            role="user",
            content="What's the weather?",
            provider_data={"reasoning_details": [{"type": "reasoning.text", "text": "..."}]},
        )

        result = model._format_message(message)

        assert "reasoning_details" not in result

    def test_no_reasoning_details_when_not_present(self):
        """Test that reasoning_details is not added when not in provider_data."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        message = Message(
            role="assistant",
            content="Response without reasoning",
            provider_data=None,
        )

        result = model._format_message(message)

        assert "reasoning_details" not in result


class TestOpenRouterStreamingReasoningDetails:
    """Test extraction of reasoning_details from streaming responses."""

    def test_extracts_reasoning_details_from_streaming_delta(self):
        """Test extraction from streaming response delta."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        # Mock streaming delta with reasoning_details
        mock_delta = MagicMock()
        mock_delta.content = "Partial"
        mock_delta.tool_calls = None
        mock_delta.reasoning_details = [{"type": "reasoning.text", "text": "step 1"}]

        mock_choice = MagicMock()
        mock_choice.delta = mock_delta
        mock_choice.finish_reason = None

        mock_chunk = MagicMock()
        mock_chunk.choices = [mock_choice]
        mock_chunk.usage = None

        result = model._parse_provider_response_delta(mock_chunk)

        assert result.provider_data is not None
        assert "reasoning_details" in result.provider_data

    def test_extracts_reasoning_from_streaming_model_extra(self):
        """Test extraction from model_extra in streaming response."""
        model = OpenRouter(id="google/gemini-2.0-flash-001")

        # Mock streaming delta with reasoning in model_extra
        mock_delta = MagicMock()
        mock_delta.content = "Partial"
        mock_delta.tool_calls = None
        mock_delta.reasoning_details = None
        mock_delta.model_extra = {"reasoning": "streaming thought"}

        mock_choice = MagicMock()
        mock_choice.delta = mock_delta
        mock_choice.finish_reason = None

        mock_chunk = MagicMock()
        mock_chunk.choices = [mock_choice]
        mock_chunk.usage = None

        result = model._parse_provider_response_delta(mock_chunk)

        assert result.provider_data is not None
        assert result.provider_data.get("reasoning_details") == "streaming thought"
