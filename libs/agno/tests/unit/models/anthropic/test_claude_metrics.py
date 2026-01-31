"""
Unit tests for Claude metrics collection with cumulative usage.

Tests the is_cumulative_usage flag behavior for Claude models,
verifying that cumulative token counts are correctly replaced (not accumulated).
"""

import os

import pytest

# Skip all tests if anthropic is not installed
pytest.importorskip("anthropic")

# Set test API key to avoid env var lookup errors
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-testing")

from agno.models.anthropic.claude import Claude
from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


def test_claude_is_cumulative_usage_flag():
    """Test that Claude has is_cumulative_usage set to True."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    assert model.is_cumulative_usage is True


def test_claude_streaming_with_cumulative_metrics():
    """
    Test that Claude correctly handles cumulative metrics during streaming.

    Simulates 3 chunks with cumulative token counts and verifies that
    metrics are replaced (not accumulated) in each chunk.
    """
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    # Chunk 1: Initial cumulative metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=200,
            output_tokens=8,
            total_tokens=208,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    # Verify first chunk metrics
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 200
    assert stream_data.response_metrics.output_tokens == 8
    assert stream_data.response_metrics.total_tokens == 208

    # Chunk 2: Cumulative metrics (total so far)
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=200,
            output_tokens=15,
            total_tokens=215,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # Verify metrics are replaced, not accumulated
    assert stream_data.response_metrics.input_tokens == 200
    assert stream_data.response_metrics.output_tokens == 15
    assert stream_data.response_metrics.total_tokens == 215

    # Chunk 3: Final cumulative metrics
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=200,
            output_tokens=30,
            total_tokens=230,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Verify final metrics reflect the cumulative total from last chunk
    assert stream_data.response_metrics.input_tokens == 200
    assert stream_data.response_metrics.output_tokens == 30
    assert stream_data.response_metrics.total_tokens == 230


def test_claude_cumulative_metrics_with_cache_tokens():
    """
    Test Claude streaming with cumulative metrics including cache tokens.

    Claude supports prompt caching, so this verifies cache-related metrics
    are also correctly replaced.
    """
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    # Chunk 1
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=2000,
            output_tokens=12,
            total_tokens=2012,
            cache_read_tokens=1500,
            cache_write_tokens=300,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 2000
    assert stream_data.response_metrics.output_tokens == 12
    assert stream_data.response_metrics.cache_read_tokens == 1500
    assert stream_data.response_metrics.cache_write_tokens == 300

    # Chunk 2 with updated cumulative metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=2000,
            output_tokens=25,
            total_tokens=2025,
            cache_read_tokens=1500,
            cache_write_tokens=300,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # All metrics should be replaced
    assert stream_data.response_metrics.input_tokens == 2000
    assert stream_data.response_metrics.output_tokens == 25
    assert stream_data.response_metrics.cache_read_tokens == 1500
    assert stream_data.response_metrics.cache_write_tokens == 300

    # Chunk 3
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=2000,
            output_tokens=42,
            total_tokens=2042,
            cache_read_tokens=1500,
            cache_write_tokens=300,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Final metrics
    assert stream_data.response_metrics.input_tokens == 2000
    assert stream_data.response_metrics.output_tokens == 42
    assert stream_data.response_metrics.total_tokens == 2042
    assert stream_data.response_metrics.cache_read_tokens == 1500
    assert stream_data.response_metrics.cache_write_tokens == 300


def test_claude_extended_thinking_metrics():
    """
    Test Claude streaming with extended thinking (reasoning) tokens.

    Claude models can use reasoning tokens for extended thinking.
    This test verifies they are correctly replaced during streaming.
    """
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    # Chunk 1 with reasoning tokens
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=500,
            output_tokens=20,
            total_tokens=520,
            reasoning_tokens=150,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 500
    assert stream_data.response_metrics.output_tokens == 20
    assert stream_data.response_metrics.reasoning_tokens == 150

    # Chunk 2 with updated cumulative metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=500,
            output_tokens=35,
            total_tokens=535,
            reasoning_tokens=250,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # Metrics should be replaced
    assert stream_data.response_metrics.input_tokens == 500
    assert stream_data.response_metrics.output_tokens == 35
    assert stream_data.response_metrics.reasoning_tokens == 250

    # Chunk 3 final metrics
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=500,
            output_tokens=50,
            total_tokens=550,
            reasoning_tokens=400,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Final metrics
    assert stream_data.response_metrics.input_tokens == 500
    assert stream_data.response_metrics.output_tokens == 50
    assert stream_data.response_metrics.total_tokens == 550
    assert stream_data.response_metrics.reasoning_tokens == 400


def test_claude_empty_metrics_initialization():
    """Test that Claude correctly initializes metrics on first chunk."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    # Verify no metrics initially
    assert stream_data.response_metrics is None

    # First chunk with metrics
    response_delta = ModelResponse(
        response_usage=Metrics(
            input_tokens=150,
            output_tokens=10,
            total_tokens=160,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta))

    # Metrics should be initialized
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.total_tokens == 160
