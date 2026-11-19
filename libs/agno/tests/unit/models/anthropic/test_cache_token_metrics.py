"""
Tests that Anthropic and Bedrock report the same gross input_tokens as every other provider.

Anthropic reports `input_tokens` NET of the prompt cache and bills
`cache_read_input_tokens` and `cache_creation_input_tokens` separately on top of it.
OpenAI reports `prompt_tokens` INCLUSIVE of the cache and exposes `cached_tokens` as a
breakdown of it.

So the same MessageMetrics field carried two different meanings depending on the provider,
and `total_tokens`, which every parser except OpenAI's derives as input + output, silently
excluded the cache on Anthropic and Bedrock. BaseMetrics.accumulate sums total_tokens across
models, so a session using both providers added two different definitions together.

Verifies that:
- input_tokens is gross, so the cache read and cache write are inside it.
- total_tokens equals input_tokens + output_tokens and covers everything billed.
- cache_read_tokens and cache_write_tokens still report the breakdown.
- Calls with no cache are completely unchanged.
"""

import importlib
import types

import pytest

from agno.models.anthropic.claude import Claude

_has_boto3 = importlib.util.find_spec("boto3") is not None
_skip_boto3 = pytest.mark.skipif(not _has_boto3, reason="boto3 not installed")


def _usage(input_tokens, output_tokens, cache_read=0, cache_write=0):
    """A minimal stand-in for an Anthropic Usage object."""
    return types.SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        server_tool_use=None,
    )


def test_cached_call_reports_every_billed_token():
    metrics = Claude(id="claude-sonnet-4-6")._get_metrics(
        _usage(input_tokens=10, output_tokens=5, cache_read=1000, cache_write=200)
    )

    # 10 uncached + 1000 read from cache + 200 written to cache
    assert metrics.input_tokens == 1210
    assert metrics.output_tokens == 5
    assert metrics.total_tokens == 1215
    assert metrics.total_tokens == metrics.input_tokens + metrics.output_tokens

    # The breakdown is still reported, now as a subset of input_tokens rather than
    # an addition to it, which is how the OpenAI parser already treats it.
    assert metrics.cache_read_tokens == 1000
    assert metrics.cache_write_tokens == 200


def test_uncached_call_is_unchanged():
    metrics = Claude(id="claude-sonnet-4-6")._get_metrics(_usage(input_tokens=10, output_tokens=5))

    assert metrics.input_tokens == 10
    assert metrics.total_tokens == 15
    assert metrics.cache_read_tokens == 0
    assert metrics.cache_write_tokens == 0


@_skip_boto3
def test_bedrock_matches_anthropic():
    """Bedrock passes Anthropic's accounting through and carried the same defect."""
    from agno.models.aws.bedrock import AwsBedrock

    metrics = AwsBedrock(id="anthropic.claude-sonnet-4-6-v1:0")._get_metrics(
        {
            "inputTokens": 10,
            "outputTokens": 5,
            "cacheReadInputTokens": 1000,
            "cacheWriteInputTokens": 200,
        }
    )

    assert metrics.input_tokens == 1210
    assert metrics.total_tokens == 1215
    assert metrics.total_tokens == metrics.input_tokens + metrics.output_tokens
