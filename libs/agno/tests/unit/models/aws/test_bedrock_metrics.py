"""Unit tests for AWS Bedrock usage parsing (#9538).

Bedrock passes through Anthropic's accounting: `inputTokens` is net of the cache
and cache reads/writes are billed on top. `AwsBedrock._get_metrics` must gross up
`input_tokens` so `total_tokens` covers everything billed.
"""

from agno.models.aws.bedrock import AwsBedrock


def _usage(input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> dict:
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheReadInputTokens": cache_read,
        "cacheWriteInputTokens": cache_write,
    }


def test_bedrock_metrics_gross_input_tokens_with_prompt_cache():
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
    metrics = model._get_metrics(_usage(input_tokens=10, output_tokens=5, cache_read=1000, cache_write=200))
    assert metrics.input_tokens == 1210
    assert metrics.cache_read_tokens == 1000
    assert metrics.cache_write_tokens == 200
    assert metrics.total_tokens == 1215


def test_bedrock_metrics_uncached_unchanged():
    model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
    metrics = model._get_metrics(_usage(input_tokens=50, output_tokens=10))
    assert metrics.input_tokens == 50
    assert metrics.total_tokens == 60
