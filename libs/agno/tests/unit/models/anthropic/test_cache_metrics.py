"""Unit tests for Anthropic prompt-cache token accounting (#9538).

Anthropic reports `input_tokens` net of the cache and bills cache reads/writes
separately. `Claude._get_metrics` must gross up `input_tokens` so `total_tokens`
covers everything billed.
"""

from anthropic.types import Usage

from agno.models.anthropic.claude import Claude


def _usage(input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
        server_tool_use=None,
    )


def test_claude_metrics_gross_input_tokens_with_prompt_cache():
    claude = Claude(id="claude-sonnet-4-6")
    metrics = claude._get_metrics(_usage(input_tokens=10, output_tokens=5, cache_read=1000, cache_write=200))
    assert metrics.input_tokens == 1210
    assert metrics.cache_read_tokens == 1000
    assert metrics.cache_write_tokens == 200
    assert metrics.total_tokens == 1215


def test_claude_metrics_uncached_unchanged():
    claude = Claude(id="claude-sonnet-4-6")
    metrics = claude._get_metrics(_usage(input_tokens=50, output_tokens=10))
    assert metrics.input_tokens == 50
    assert metrics.total_tokens == 60
