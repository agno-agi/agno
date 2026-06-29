"""Regression tests: OpenAI Chat + Responses parsers surface a normalized finish_reason."""

from types import SimpleNamespace

from agno.models.finish_reason import FinishReason
from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses


def _chat_response(finish_reason: str):
    message = SimpleNamespace(role="assistant", content="partial answer", tool_calls=None, audio=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None, id=None, system_fingerprint=None, model_extra=None)


def test_chat_non_stream_length():
    model = OpenAIChat(id="gpt-4o")
    result = model._parse_provider_response(_chat_response("length"))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "length"


def test_chat_non_stream_content_filter():
    model = OpenAIChat(id="gpt-4o")
    result = model._parse_provider_response(_chat_response("content_filter"))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.CONTENT_FILTER
    assert result.provider_data["native_finish_reason"] == "content_filter"


def test_chat_non_stream_tool_calls():
    model = OpenAIChat(id="gpt-4o")
    result = model._parse_provider_response(_chat_response("tool_calls"))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.TOOL_CALL


def test_chat_stream_length():
    model = OpenAIChat(id="gpt-4o")
    choice_delta = SimpleNamespace(content=None, tool_calls=None)
    choice = SimpleNamespace(delta=choice_delta, finish_reason="length")
    chunk = SimpleNamespace(choices=[choice], usage=None)

    result = model._parse_provider_response_delta(chunk)  # type: ignore[arg-type]

    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "length"


def test_responses_non_stream_incomplete_max_output_tokens():
    model = OpenAIResponses(id="gpt-5")
    response = SimpleNamespace(
        error=None,
        id=None,
        output=[],
        usage=None,
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
    )
    result = model._parse_provider_response(response)  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "max_output_tokens"


def test_responses_non_stream_incomplete_content_filter():
    model = OpenAIResponses(id="gpt-5")
    response = SimpleNamespace(
        error=None,
        id=None,
        output=[],
        usage=None,
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="content_filter"),
    )
    result = model._parse_provider_response(response)  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.CONTENT_FILTER
    assert result.provider_data["native_finish_reason"] == "content_filter"


def test_responses_non_stream_completed_maps_to_stop():
    model = OpenAIResponses(id="gpt-5")
    response = SimpleNamespace(
        error=None,
        id=None,
        output=[],
        usage=None,
        status="completed",
        incomplete_details=None,
    )
    result = model._parse_provider_response(response)  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.STOP
    assert result.provider_data["native_finish_reason"] == "completed"
