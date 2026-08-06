"""Regression tests: the Gemini parser surfaces a normalized finish_reason.

Feeds the parser both a raw string and a real google.genai FinishReason enum member, because
``str(member)`` renders ``"FinishReason.MAX_TOKENS"`` and would silently miss the map if the
mapper keyed off ``str()`` instead of ``.name``.
"""

from types import SimpleNamespace

from google.genai.types import FinishReason as GeminiSDKFinishReason

from agno.models.finish_reason import FinishReason
from agno.models.google.gemini import Gemini


def _response(finish_reason):
    candidate = SimpleNamespace(finish_reason=finish_reason, content=None)
    return SimpleNamespace(candidates=[candidate], usage_metadata=None)


def test_non_stream_max_tokens_from_real_enum_member():
    model = Gemini(id="gemini-2.0-flash")
    result = model._parse_provider_response(_response(GeminiSDKFinishReason.MAX_TOKENS))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "MAX_TOKENS"


def test_non_stream_safety_from_string():
    model = Gemini(id="gemini-2.0-flash")
    result = model._parse_provider_response(_response("SAFETY"))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.CONTENT_FILTER
    assert result.provider_data["native_finish_reason"] == "SAFETY"


def test_stream_max_tokens_from_real_enum_member():
    model = Gemini(id="gemini-2.0-flash")
    result = model._parse_provider_response_delta(_response(GeminiSDKFinishReason.MAX_TOKENS))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "MAX_TOKENS"


def test_non_stream_unknown_reason_degrades_to_unknown():
    model = Gemini(id="gemini-2.0-flash")
    result = model._parse_provider_response(_response("FINISH_REASON_UNSPECIFIED"))  # type: ignore[arg-type]
    assert result.finish_reason == FinishReason.UNKNOWN
    assert result.provider_data["native_finish_reason"] == "FINISH_REASON_UNSPECIFIED"
