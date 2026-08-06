"""Regression test: the native Cerebras parser surfaces a normalized finish_reason (OpenAI-shaped)."""

from types import SimpleNamespace

from agno.models.cerebras.cerebras import Cerebras
from agno.models.finish_reason import FinishReason


def test_non_stream_length():
    model = Cerebras(id="llama-3.3-70b")
    message = SimpleNamespace(role="assistant", content="partial", tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="length")
    response = SimpleNamespace(choices=[choice], usage=None)

    result = model._parse_provider_response(response)  # type: ignore[arg-type]

    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "length"


def test_stream_length():
    model = Cerebras(id="llama-3.3-70b")
    choice_delta = SimpleNamespace(content=None, tool_calls=None)
    choice = SimpleNamespace(delta=choice_delta, finish_reason="length")
    response = SimpleNamespace(choices=[choice], usage=None)

    result = model._parse_provider_response_delta(response)  # type: ignore[arg-type]

    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "length"
