"""
Unit tests for is_cumulative_usage behavior in _populate_stream_data.

Tests that the is_cumulative_usage flag correctly controls whether metrics
are accumulated (+=) or replaced (=) during streaming.
"""

import os

# Set test API key to avoid env var lookup errors
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse


def test_accumulate_metrics_when_is_cumulative_usage_false():
    """Test that metrics are accumulated when is_cumulative_usage is False (default)."""
    model = OpenAIChat(id="gpt-4o")
    assert model.is_cumulative_usage is False

    stream_data = MessageData()

    # First chunk with metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=5,
            total_tokens=105,
        )
    )

    # Process first chunk
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.total_tokens == 105

    # Second chunk with metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=0,
            output_tokens=3,
            total_tokens=3,
        )
    )

    # Process second chunk
    list(model._populate_stream_data(stream_data, response_delta_2))

    # Metrics should be accumulated (100 + 0 = 100, 5 + 3 = 8, 105 + 3 = 108)
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 8
    assert stream_data.response_metrics.total_tokens == 108

    # Third chunk with metrics
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=0,
            output_tokens=2,
            total_tokens=2,
        )
    )

    # Process third chunk
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Metrics should be accumulated (100 + 0 = 100, 8 + 2 = 10, 108 + 2 = 110)
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.total_tokens == 110


def test_replace_metrics_when_is_cumulative_usage_true():
    """Test that metrics are replaced when is_cumulative_usage is True."""
    model = OpenAIChat(id="gpt-4o")
    model.is_cumulative_usage = True

    stream_data = MessageData()

    # First chunk with cumulative metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=1,
            total_tokens=101,
        )
    )

    # Process first chunk
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 1
    assert stream_data.response_metrics.total_tokens == 101

    # Second chunk with cumulative metrics (cumulative count)
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=2,
            total_tokens=102,
        )
    )

    # Process second chunk
    list(model._populate_stream_data(stream_data, response_delta_2))

    # Metrics should be replaced, not accumulated
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 2
    assert stream_data.response_metrics.total_tokens == 102

    # Third chunk with cumulative metrics (cumulative count)
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=5,
            total_tokens=105,
        )
    )

    # Process third chunk
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Metrics should be replaced, not accumulated
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.total_tokens == 105


def test_cumulative_usage_with_detailed_metrics():
    """Test that cumulative usage works correctly with detailed metrics like reasoning_tokens."""
    model = OpenAIChat(id="gpt-4o")
    model.is_cumulative_usage = True

    stream_data = MessageData()

    # First chunk with detailed metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=5,
            total_tokens=105,
            reasoning_tokens=10,
            cache_read_tokens=50,
        )
    )

    # Process first chunk
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.reasoning_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 50

    # Second chunk with updated cumulative metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=10,
            total_tokens=110,
            reasoning_tokens=20,
            cache_read_tokens=50,
        )
    )

    # Process second chunk
    list(model._populate_stream_data(stream_data, response_delta_2))

    # All metrics should be replaced with the new cumulative values
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.reasoning_tokens == 20
    assert stream_data.response_metrics.cache_read_tokens == 50


def test_accumulate_usage_with_detailed_metrics():
    """Test that accumulated usage works correctly with detailed metrics."""
    model = OpenAIChat(id="gpt-4o")
    assert model.is_cumulative_usage is False

    stream_data = MessageData()

    # First chunk with detailed metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=5,
            total_tokens=105,
            reasoning_tokens=10,
            cache_read_tokens=50,
        )
    )

    # Process first chunk
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.reasoning_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 50

    # Second chunk with incremental metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=0,
            output_tokens=3,
            total_tokens=3,
            reasoning_tokens=5,
            cache_read_tokens=0,
        )
    )

    # Process second chunk
    list(model._populate_stream_data(stream_data, response_delta_2))

    # All metrics should be accumulated
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 8
    assert stream_data.response_metrics.reasoning_tokens == 15
    assert stream_data.response_metrics.cache_read_tokens == 50
