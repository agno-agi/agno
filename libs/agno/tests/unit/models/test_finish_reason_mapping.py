"""Unit tests for the normalized cross-provider finish_reason mappers.

Each mapper is fed (a) the raw provider string, (b) a real SDK enum member where one exists,
and (c) an unmapped value. The real-enum case is what proves the ``str(enum)`` trap is handled:
``str(google.genai.types.FinishReason.MAX_TOKENS)`` renders ``"FinishReason.MAX_TOKENS"``, so the
mapper must key off the member ``.name`` instead.
"""

import pytest

from agno.models.finish_reason import (
    FinishReason,
    map_anthropic_finish_reason,
    map_bedrock_finish_reason,
    map_cerebras_finish_reason,
    map_gemini_finish_reason,
    map_groq_finish_reason,
    map_openai_finish_reason,
    map_openai_responses_finish_reason,
    warn_if_truncated,
)


def test_finish_reason_is_str_backed():
    """The enum compares equal to its string value, keeping the field backward compatible."""
    assert FinishReason.LENGTH == "length"
    assert FinishReason.STOP == "stop"
    assert isinstance(FinishReason.LENGTH, str)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("end_turn", FinishReason.STOP),
        ("stop_sequence", FinishReason.STOP),
        ("max_tokens", FinishReason.LENGTH),
        ("model_context_window_exceeded", FinishReason.LENGTH),
        ("compaction", FinishReason.LENGTH),
        ("tool_use", FinishReason.TOOL_CALL),
        ("pause_turn", FinishReason.PAUSE),
        ("refusal", FinishReason.REFUSAL),
    ],
)
def test_anthropic_mapping(raw, expected):
    finish_reason, native = map_anthropic_finish_reason(raw)
    assert finish_reason == expected
    assert native == raw


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("stop", FinishReason.STOP),
        ("length", FinishReason.LENGTH),
        ("tool_calls", FinishReason.TOOL_CALL),
        ("function_call", FinishReason.TOOL_CALL),
        ("content_filter", FinishReason.CONTENT_FILTER),
    ],
)
def test_openai_mapping(raw, expected):
    finish_reason, native = map_openai_finish_reason(raw)
    assert finish_reason == expected
    assert native == raw


def test_groq_and_cerebras_reuse_openai_mapping():
    assert map_groq_finish_reason("length") == (FinishReason.LENGTH, "length")
    assert map_cerebras_finish_reason("length") == (FinishReason.LENGTH, "length")
    assert map_groq_finish_reason("tool_calls")[0] == FinishReason.TOOL_CALL


@pytest.mark.parametrize(
    "status,incomplete_reason,expected,expected_native",
    [
        ("completed", None, FinishReason.STOP, "completed"),
        ("incomplete", "max_output_tokens", FinishReason.LENGTH, "max_output_tokens"),
        ("incomplete", "content_filter", FinishReason.CONTENT_FILTER, "content_filter"),
        ("incomplete", None, FinishReason.UNKNOWN, "incomplete"),
        ("incomplete", "something_new", FinishReason.UNKNOWN, "something_new"),
    ],
)
def test_openai_responses_mapping(status, incomplete_reason, expected, expected_native):
    finish_reason, native = map_openai_responses_finish_reason(status, incomplete_reason)
    assert finish_reason == expected
    assert native == expected_native


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("STOP", FinishReason.STOP),
        ("MAX_TOKENS", FinishReason.LENGTH),
        ("SAFETY", FinishReason.CONTENT_FILTER),
        ("RECITATION", FinishReason.CONTENT_FILTER),
        ("BLOCKLIST", FinishReason.CONTENT_FILTER),
        ("PROHIBITED_CONTENT", FinishReason.CONTENT_FILTER),
        ("SPII", FinishReason.CONTENT_FILTER),
        ("LANGUAGE", FinishReason.CONTENT_FILTER),
        ("IMAGE_SAFETY", FinishReason.CONTENT_FILTER),
        ("MALFORMED_FUNCTION_CALL", FinishReason.ERROR),
    ],
)
def test_gemini_mapping_from_string(raw, expected):
    finish_reason, native = map_gemini_finish_reason(raw)
    assert finish_reason == expected
    assert native == raw


def test_gemini_mapping_from_real_enum_member():
    """A real google.genai FinishReason member must map by .name, not str(member)."""
    from google.genai.types import FinishReason as GeminiSDKFinishReason

    # str(member) renders "FinishReason.MAX_TOKENS", which would never match the table.
    assert str(GeminiSDKFinishReason.MAX_TOKENS) != "MAX_TOKENS"

    finish_reason, native = map_gemini_finish_reason(GeminiSDKFinishReason.MAX_TOKENS)
    assert finish_reason == FinishReason.LENGTH
    assert native == "MAX_TOKENS"

    finish_reason, native = map_gemini_finish_reason(GeminiSDKFinishReason.SAFETY)
    assert finish_reason == FinishReason.CONTENT_FILTER
    assert native == "SAFETY"


def test_bedrock_mapping():
    assert map_bedrock_finish_reason("guardrail_intervened")[0] == FinishReason.CONTENT_FILTER
    assert map_bedrock_finish_reason("content_filtered")[0] == FinishReason.CONTENT_FILTER
    assert map_bedrock_finish_reason("max_tokens")[0] == FinishReason.LENGTH


@pytest.mark.parametrize(
    "mapper,raw",
    [
        (map_anthropic_finish_reason, "some_unknown_reason"),
        (map_openai_finish_reason, "some_unknown_reason"),
        (map_gemini_finish_reason, "FINISH_REASON_UNSPECIFIED"),
        (map_gemini_finish_reason, "OTHER"),
        (map_bedrock_finish_reason, "some_unknown_reason"),
    ],
)
def test_unknown_value_maps_to_unknown_and_preserves_raw(mapper, raw):
    """The anti-crash guarantee: an unmapped value degrades to UNKNOWN, raw preserved, no raise."""
    finish_reason, native = mapper(raw)
    assert finish_reason == FinishReason.UNKNOWN
    assert native == raw


def test_unknown_never_maps_to_stop():
    """We never copy the LiteLLM default-to-stop footgun."""
    finish_reason, _ = map_openai_finish_reason("brand_new_reason")
    assert finish_reason != FinishReason.STOP
    assert finish_reason == FinishReason.UNKNOWN


class _FakeRun:
    """Minimal stand-in for a RunOutput; warn_if_truncated only needs attribute get/set."""


def test_warn_if_truncated_dedupes_per_run():
    run = _FakeRun()
    warning_calls = []

    import agno.models.finish_reason as module

    original = module.log_warning
    module.log_warning = lambda msg: warning_calls.append(msg)
    try:
        warn_if_truncated(run, FinishReason.LENGTH)
        warn_if_truncated(run, FinishReason.LENGTH)  # second call must be deduped
        warn_if_truncated(run, FinishReason.STOP)  # non-LENGTH must never warn
    finally:
        module.log_warning = original

    assert len(warning_calls) == 1


def test_warn_if_truncated_silent_on_non_length():
    run = _FakeRun()
    warning_calls = []

    import agno.models.finish_reason as module

    original = module.log_warning
    module.log_warning = lambda msg: warning_calls.append(msg)
    try:
        warn_if_truncated(run, FinishReason.STOP)
        warn_if_truncated(run, FinishReason.TOOL_CALL)
        warn_if_truncated(run, None)
    finally:
        module.log_warning = original

    assert warning_calls == []
