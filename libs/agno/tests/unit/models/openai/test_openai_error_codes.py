"""Tests for provider error code preservation on ModelProviderError (OpenAI models)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIStatusError

from agno.exceptions import ContextWindowExceededError, ModelProviderError
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses


def _make_fake_client() -> MagicMock:
    client = MagicMock()
    client.is_closed.return_value = False
    return client


def _api_status_error(status_code: int, code: str, message: str) -> APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/test")
    response = httpx.Response(
        status_code,
        json={"error": {"message": message, "type": "invalid_request_error", "param": None, "code": code}},
        request=request,
    )
    return APIStatusError(message, response=response, body=None)


def _make_assistant_message() -> Message:
    return Message(role="assistant")


class TestResponsesErrorCodePreserved:
    def test_api_status_error_code_preserved(self):
        """The provider error code from a 4xx response body is carried on ModelProviderError."""
        model = OpenAIResponses(id="gpt-4.1-mini")
        fake_client = _make_fake_client()
        fake_client.responses.create.side_effect = _api_status_error(
            400, "invalid_prompt", "Invalid prompt: your prompt was flagged"
        )
        model.client = fake_client

        with patch.object(model, "_format_messages", return_value=[]):
            with pytest.raises(ModelProviderError) as exc_info:
                model.invoke(messages=[Message(role="user", content="hi")], assistant_message=_make_assistant_message())

        assert exc_info.value.code == "invalid_prompt"
        assert exc_info.value.status_code == 400
        assert isinstance(exc_info.value.__cause__, APIStatusError)

    def test_context_length_exceeded_code_preserved(self):
        """context_length_exceeded still raises ContextWindowExceededError, now carrying the code."""
        model = OpenAIResponses(id="gpt-4.1-mini")
        fake_client = _make_fake_client()
        fake_client.responses.create.side_effect = _api_status_error(
            400, "context_length_exceeded", "This model's maximum context length is exceeded"
        )
        model.client = fake_client

        with patch.object(model, "_format_messages", return_value=[]):
            with pytest.raises(ContextWindowExceededError) as exc_info:
                model.invoke(messages=[Message(role="user", content="hi")], assistant_message=_make_assistant_message())

        assert exc_info.value.code == "context_length_exceeded"


class TestChatErrorCodePreserved:
    def test_api_status_error_code_preserved(self):
        """The provider error code from a 4xx response body is carried on ModelProviderError."""
        model = OpenAIChat(id="gpt-4o-mini")
        fake_client = _make_fake_client()
        fake_client.chat.completions.create.side_effect = _api_status_error(
            400, "invalid_prompt", "Invalid prompt: your prompt was flagged"
        )
        model.client = fake_client

        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=[Message(role="user", content="hi")], assistant_message=_make_assistant_message())

        assert exc_info.value.code == "invalid_prompt"
        assert exc_info.value.status_code == 400
        assert isinstance(exc_info.value.__cause__, APIStatusError)

    def test_context_length_exceeded_code_preserved(self):
        model = OpenAIChat(id="gpt-4o-mini")
        fake_client = _make_fake_client()
        fake_client.chat.completions.create.side_effect = _api_status_error(
            400, "context_length_exceeded", "This model's maximum context length is exceeded"
        )
        model.client = fake_client

        with pytest.raises(ContextWindowExceededError) as exc_info:
            model.invoke(messages=[Message(role="user", content="hi")], assistant_message=_make_assistant_message())

        assert exc_info.value.code == "context_length_exceeded"

    def test_error_without_code_defaults_to_none(self):
        """A 4xx body with no code field yields code=None (best-effort contract)."""
        model = OpenAIChat(id="gpt-4o-mini")
        fake_client = _make_fake_client()
        request = httpx.Request("POST", "https://api.openai.com/v1/test")
        response = httpx.Response(
            400, json={"error": {"message": "Bad request", "type": "invalid_request_error"}}, request=request
        )
        fake_client.chat.completions.create.side_effect = APIStatusError("Bad request", response=response, body=None)
        model.client = fake_client

        with pytest.raises(ModelProviderError) as exc_info:
            model.invoke(messages=[Message(role="user", content="hi")], assistant_message=_make_assistant_message())

        assert exc_info.value.code is None
