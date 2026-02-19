"""Unit tests for Bedrock Claude structured output parsing.

Verifies that when _parse_provider_response successfully parses JSON into
model_response.parsed, it also transfers the parsed Pydantic model to
model_response.content (fix for Issue #6194).
"""

from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.models.anthropic.claude import Claude


class MovieReview(BaseModel):
    title: str
    rating: float
    summary: str


def _make_text_block(text: str):
    """Create a mock text content block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = None
    return block


def _make_response(text: str, stop_reason: str = "end_turn"):
    """Create a mock Anthropic Message response with a text block."""
    response = MagicMock()
    response.role = "assistant"
    response.stop_reason = stop_reason
    response.content = [_make_text_block(text)]
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    response.usage.cache_read_input_tokens = 0
    response.usage.cache_creation_input_tokens = 0
    response.usage.server_tool_use = None
    response.usage.service_tier = None
    return response


class TestStructuredOutputTransferToContent:
    """Tests for parsed structured output being transferred to content."""

    def test_parsed_transferred_to_content(self):
        """When response_format is a Pydantic model and JSON parses successfully,
        model_response.parsed should be set AND model_response.content should be
        the same parsed Pydantic model instance."""
        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        json_text = '{"title": "Inception", "rating": 9.5, "summary": "A mind-bending thriller"}'
        response = _make_response(json_text)

        model_response = claude._parse_provider_response(response, response_format=MovieReview)

        assert model_response.parsed is not None
        assert isinstance(model_response.parsed, MovieReview)
        assert model_response.parsed.title == "Inception"
        assert model_response.parsed.rating == 9.5
        assert model_response.parsed.summary == "A mind-bending thriller"

        # The key assertion: content should be the parsed Pydantic model, not raw text
        assert model_response.content is model_response.parsed
        assert isinstance(model_response.content, MovieReview)

    def test_content_remains_text_without_response_format(self):
        """When response_format is None, content should remain as raw text
        and parsed should be None."""
        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        text = "This is a normal text response"
        response = _make_response(text)

        model_response = claude._parse_provider_response(response, response_format=None)

        assert model_response.parsed is None
        assert model_response.content == text

    def test_content_remains_text_with_dict_response_format(self):
        """When response_format is a dict (e.g., json_object mode), content should
        remain as raw text and parsed should be None."""
        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        json_text = '{"title": "Inception", "rating": 9.5}'
        response = _make_response(json_text)

        model_response = claude._parse_provider_response(response, response_format={"type": "json_object"})

        assert model_response.parsed is None
        assert model_response.content == json_text

    def test_content_not_overwritten_on_parse_failure(self):
        """When JSON parsing fails, content should remain as the raw text
        and parsed should be None."""
        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        invalid_json = "This is not valid JSON"
        response = _make_response(invalid_json)

        model_response = claude._parse_provider_response(response, response_format=MovieReview)

        assert model_response.parsed is None
        assert model_response.content == invalid_json

    def test_content_not_overwritten_on_validation_failure(self):
        """When JSON parses but Pydantic validation fails, content should remain
        as raw text and parsed should be None."""
        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        # Valid JSON but missing required fields
        bad_json = '{"title": "Inception"}'
        response = _make_response(bad_json)

        model_response = claude._parse_provider_response(response, response_format=MovieReview)

        assert model_response.parsed is None
        assert model_response.content == bad_json


class TestStreamingStructuredOutputTransferToContent:
    """Tests for parsed structured output in streaming being transferred to content."""

    def test_streaming_parsed_transferred_to_content(self):
        """In streaming mode, when the final MessageStopEvent has structured output,
        model_response.parsed should be set AND model_response.content should be
        the parsed Pydantic model instance."""
        from anthropic.types import MessageStopEvent

        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        json_text = '{"title": "Inception", "rating": 9.5, "summary": "A mind-bending thriller"}'

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json_text
        text_block.citations = None

        stop_event = MagicMock(spec=MessageStopEvent)
        stop_event.message = MagicMock()
        stop_event.message.content = [text_block]
        stop_event.message.usage = MagicMock()
        stop_event.message.usage.input_tokens = 100
        stop_event.message.usage.output_tokens = 50
        stop_event.message.usage.cache_read_input_tokens = 0
        stop_event.message.usage.cache_creation_input_tokens = 0
        stop_event.message.usage.server_tool_use = None
        stop_event.message.usage.service_tier = None

        model_response = claude._parse_provider_response_delta(stop_event, response_format=MovieReview)

        assert model_response.parsed is not None
        assert isinstance(model_response.parsed, MovieReview)
        assert model_response.parsed.title == "Inception"

        # The key assertion: content should be the parsed Pydantic model
        assert model_response.content is model_response.parsed
        assert isinstance(model_response.content, MovieReview)

    def test_streaming_no_parse_without_response_format(self):
        """In streaming mode, when no response_format is given,
        parsed should be None and content should be empty string (streaming default)."""
        from anthropic.types import MessageStopEvent

        claude = Claude.__new__(Claude)
        claude.context_management = None
        claude.skills = None

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Normal text response"
        text_block.citations = None

        stop_event = MagicMock(spec=MessageStopEvent)
        stop_event.message = MagicMock()
        stop_event.message.content = [text_block]
        stop_event.message.usage = MagicMock()
        stop_event.message.usage.input_tokens = 100
        stop_event.message.usage.output_tokens = 50
        stop_event.message.usage.cache_read_input_tokens = 0
        stop_event.message.usage.cache_creation_input_tokens = 0
        stop_event.message.usage.server_tool_use = None
        stop_event.message.usage.service_tier = None

        model_response = claude._parse_provider_response_delta(stop_event, response_format=None)

        assert model_response.parsed is None
        # In streaming, content is set to "" at MessageStopEvent to avoid duplication
        assert model_response.content == ""
