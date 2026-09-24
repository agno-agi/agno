"""
Unit tests for truncated/incomplete response detection in OpenAI models.

Verifies that OpenAIChat and OpenAIResponses raise ModelProviderError when the
model returns a response with no usable content due to context length exhaustion
or max_output_tokens truncation.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses

# ---------------------------------------------------------------------------
# Fakes for OpenAIChat (Chat Completions API)
# ---------------------------------------------------------------------------


class _FakeChatMessage:
    def __init__(
        self,
        content: Optional[str] = None,
        role: str = "assistant",
        tool_calls: Optional[list] = None,
    ):
        self.content = content
        self.role = role
        self.tool_calls = tool_calls
        self.audio = None
        self.refusal = None
        self.annotations = None


class _FakeChatChoice:
    def __init__(self, message: _FakeChatMessage, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason


class _FakeChatCompletion:
    def __init__(self, choices: list, usage=None, _id: str = "chatcmpl-1"):
        self.choices = choices
        self.usage = usage
        self.error = None
        self.id = _id
        self.system_fingerprint = None
        self.model_extra = None


# ---------------------------------------------------------------------------
# Fakes for OpenAIResponses (Responses API)
# ---------------------------------------------------------------------------


class _FakeIncompleteDetails:
    def __init__(self, reason: str):
        self.reason = reason


class _FakeResponsesResponse:
    def __init__(
        self,
        *,
        _id: str = "resp_1",
        output: Optional[List[Any]] = None,
        output_text: str = "",
        status: str = "completed",
        incomplete_details: Optional[_FakeIncompleteDetails] = None,
        usage: Optional[Dict[str, Any]] = None,
        error: Optional[Any] = None,
    ):
        self.id = _id
        self.output = output or []
        self.output_text = output_text
        self.status = status
        self.incomplete_details = incomplete_details
        self.usage = usage
        self.error = error


class _FakeStreamEvent:
    def __init__(self, *, type: str, response: Any = None, **kwargs):
        self.type = type
        self.response = response
        for k, v in kwargs.items():
            setattr(self, k, v)


# ===========================================================================
# OpenAIChat tests
# ===========================================================================


class TestOpenAIChatTruncatedResponse:
    """Tests for truncated response detection in OpenAIChat._parse_provider_response."""

    def test_finish_reason_length_no_content_no_tools_raises(self):
        """When finish_reason=length and response has no content or tool calls, raise."""
        model = OpenAIChat(id="gpt-4o")
        message = _FakeChatMessage(content=None, tool_calls=None)
        choice = _FakeChatChoice(message=message, finish_reason="length")
        response = _FakeChatCompletion(choices=[choice])

        with pytest.raises(ModelProviderError, match="truncated"):
            model._parse_provider_response(response)  # type: ignore[arg-type]

    def test_finish_reason_length_with_content_does_not_raise(self):
        """When finish_reason=length but there IS partial content, don't raise."""
        model = OpenAIChat(id="gpt-4o")
        message = _FakeChatMessage(content="partial answer...")
        choice = _FakeChatChoice(message=message, finish_reason="length")
        response = _FakeChatCompletion(choices=[choice])

        result = model._parse_provider_response(response)  # type: ignore[arg-type]
        assert result.content == "partial answer..."

    def test_finish_reason_length_with_tool_calls_does_not_raise(self):
        """When finish_reason=length but there are tool calls, don't raise."""
        model = OpenAIChat(id="gpt-4o")
        tool_call = MagicMock()
        tool_call.model_dump.return_value = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search", "arguments": "{}"},
        }
        message = _FakeChatMessage(content=None, tool_calls=[tool_call])
        choice = _FakeChatChoice(message=message, finish_reason="length")
        response = _FakeChatCompletion(choices=[choice])

        result = model._parse_provider_response(response)  # type: ignore[arg-type]
        assert result.tool_calls is not None

    def test_finish_reason_stop_no_content_does_not_raise(self):
        """Normal finish_reason=stop with no content (e.g. tool-only response) shouldn't raise."""
        model = OpenAIChat(id="gpt-4o")
        tool_call = MagicMock()
        tool_call.model_dump.return_value = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search", "arguments": "{}"},
        }
        message = _FakeChatMessage(content=None, tool_calls=[tool_call])
        choice = _FakeChatChoice(message=message, finish_reason="stop")
        response = _FakeChatCompletion(choices=[choice])

        result = model._parse_provider_response(response)  # type: ignore[arg-type]
        assert result.tool_calls is not None


# ===========================================================================
# OpenAIResponses tests (non-streaming)
# ===========================================================================


class TestOpenAIResponsesIncomplete:
    """Tests for incomplete response detection in OpenAIResponses._parse_provider_response."""

    def test_incomplete_no_content_raises(self):
        """When status=incomplete and no output_text, raise."""
        model = OpenAIResponses(id="gpt-4o")
        response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
            output_text="",
        )

        with pytest.raises(ModelProviderError, match="incomplete"):
            model._parse_provider_response(response)  # type: ignore[arg-type]

    def test_incomplete_with_partial_content_does_not_raise(self):
        """When status=incomplete but there IS partial output_text, don't raise (log warning only)."""
        model = OpenAIResponses(id="gpt-4o")

        # Need a message-type output item so _parse_provider_response processes content
        fake_output = MagicMock()
        fake_output.type = "message"

        response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
            output_text="partial answer here...",
            output=[fake_output],
        )

        result = model._parse_provider_response(response)  # type: ignore[arg-type]
        assert result.content == "partial answer here..."

    def test_incomplete_no_details_raises(self):
        """When status=incomplete with no incomplete_details, still raise with reason=unknown."""
        model = OpenAIResponses(id="gpt-4o")
        response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=None,
            output_text="",
        )

        with pytest.raises(ModelProviderError, match="unknown"):
            model._parse_provider_response(response)  # type: ignore[arg-type]

    def test_incomplete_with_function_call_does_not_raise(self):
        """When status=incomplete but output contains function_call items, don't raise."""
        model = OpenAIResponses(id="gpt-4o")

        fake_function_call = MagicMock()
        fake_function_call.type = "function_call"
        fake_function_call.name = "search"
        fake_function_call.arguments = "{}"
        fake_function_call.call_id = "call_1"

        response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
            output_text="",
            output=[fake_function_call],
        )

        result = model._parse_provider_response(response)  # type: ignore[arg-type]
        # Should not raise — function_call items count as partial content
        assert result is not None

    def test_completed_status_does_not_raise(self):
        """Normal completed response should not raise."""
        model = OpenAIResponses(id="gpt-4o")

        fake_output = MagicMock()
        fake_output.type = "message"

        response = _FakeResponsesResponse(
            status="completed",
            output_text="full answer",
            output=[fake_output],
        )

        result = model._parse_provider_response(response)  # type: ignore[arg-type]
        assert result.content == "full answer"


# ===========================================================================
# OpenAIResponses tests (streaming)
# ===========================================================================


class TestOpenAIResponsesStreamingIncomplete:
    """Tests for incomplete response detection in streaming via _parse_provider_response_delta."""

    def test_streaming_incomplete_no_content_raises(self):
        """When response.completed event has status=incomplete and assistant has no content, raise."""
        model = OpenAIResponses(id="gpt-4o")
        assistant_message = Message(role="assistant")  # no content

        fake_response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
            output_text="",
        )
        event = _FakeStreamEvent(type="response.completed", response=fake_response)

        with pytest.raises(ModelProviderError, match="incomplete"):
            model._parse_provider_response_delta(event, assistant_message, {})  # type: ignore[arg-type]

    def test_streaming_incomplete_with_content_does_not_raise(self):
        """When response.completed has status=incomplete but assistant has content, don't raise."""
        model = OpenAIResponses(id="gpt-4o")
        assistant_message = Message(role="assistant", content="streamed partial content")

        fake_response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
            output_text="streamed partial content",
        )
        # Need output list for metrics parsing
        fake_response.output = []
        event = _FakeStreamEvent(type="response.completed", response=fake_response)

        result, _ = model._parse_provider_response_delta(event, assistant_message, {})  # type: ignore[arg-type]
        # Should return a ModelResponse (metrics) without raising
        assert result is not None

    def test_streaming_incomplete_with_tool_calls_does_not_raise(self):
        """When response.completed has status=incomplete but assistant has tool_calls, don't raise."""
        model = OpenAIResponses(id="gpt-4o")
        assistant_message = Message(role="assistant")  # no content
        assistant_message.tool_calls = [
            {"call_id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
        ]

        fake_response = _FakeResponsesResponse(
            status="incomplete",
            incomplete_details=_FakeIncompleteDetails(reason="max_output_tokens"),
            output_text="",
        )
        fake_response.output = []
        event = _FakeStreamEvent(type="response.completed", response=fake_response)

        result, _ = model._parse_provider_response_delta(event, assistant_message, {})  # type: ignore[arg-type]
        # Should not raise — tool_calls count as partial content
        assert result is not None

    def test_streaming_completed_does_not_raise(self):
        """Normal completed streaming response should not raise."""
        model = OpenAIResponses(id="gpt-4o")
        assistant_message = Message(role="assistant", content="full response")

        fake_response = _FakeResponsesResponse(
            status="completed",
            output_text="full response",
        )
        fake_response.output = []
        event = _FakeStreamEvent(type="response.completed", response=fake_response)

        result, _ = model._parse_provider_response_delta(event, assistant_message, {})  # type: ignore[arg-type]
        assert result is not None
