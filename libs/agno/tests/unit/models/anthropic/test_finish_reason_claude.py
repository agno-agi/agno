"""Regression tests: Claude parsers surface a normalized finish_reason.

Covers the bug where a truncated generation (stop_reason="max_tokens") was indistinguishable
from a clean one because the stop reason was only ever read to detect tool calls.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from anthropic.types import MessageStopEvent

from agno.models.anthropic.claude import Claude
from agno.models.finish_reason import FinishReason


def test_non_stream_max_tokens_maps_to_length():
    claude = Claude(id="claude-sonnet-4-5-20250929")
    response = SimpleNamespace(role="assistant", content=[], stop_reason="max_tokens", usage=None)

    result = claude._parse_provider_response(response)  # type: ignore[arg-type]

    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data is not None
    assert result.provider_data["native_finish_reason"] == "max_tokens"


def test_non_stream_end_turn_maps_to_stop():
    claude = Claude(id="claude-sonnet-4-5-20250929")
    response = SimpleNamespace(role="assistant", content=[], stop_reason="end_turn", usage=None)

    result = claude._parse_provider_response(response)  # type: ignore[arg-type]

    assert result.finish_reason == FinishReason.STOP
    assert result.provider_data["native_finish_reason"] == "end_turn"


def test_non_stream_unknown_stop_reason_degrades_to_unknown():
    claude = Claude(id="claude-sonnet-4-5-20250929")
    response = SimpleNamespace(role="assistant", content=[], stop_reason="some_new_anthropic_reason", usage=None)

    result = claude._parse_provider_response(response)  # type: ignore[arg-type]

    assert result.finish_reason == FinishReason.UNKNOWN
    assert result.provider_data["native_finish_reason"] == "some_new_anthropic_reason"


def test_stream_message_stop_max_tokens_maps_to_length():
    claude = Claude(id="claude-sonnet-4-5-20250929")
    event = MagicMock(spec=MessageStopEvent)
    event.message = SimpleNamespace(content=[], usage=None, stop_reason="max_tokens", container=None)

    result = claude._parse_provider_response_delta(event)

    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data is not None
    assert result.provider_data["native_finish_reason"] == "max_tokens"


def test_aws_claude_inherits_anthropic_mapping():
    """AWS Bedrock Claude subclasses AnthropicClaude and does not override the parser.

    Proves the inherited mapping fires on Anthropic-style stop_reason strings (not Converse
    guardrail strings, which travel through the separate aws/bedrock.py parser).
    """
    try:
        from agno.models.aws.claude import Claude as AwsClaude
    except ImportError:
        pytest.skip("aws extras (boto3 / anthropic[bedrock]) not installed")

    model = AwsClaude(id="anthropic.claude-sonnet-4-5-20250929-v1:0")
    response = SimpleNamespace(role="assistant", content=[], stop_reason="max_tokens", usage=None)

    result = model._parse_provider_response(response)

    assert result.finish_reason == FinishReason.LENGTH
    assert result.provider_data["native_finish_reason"] == "max_tokens"
