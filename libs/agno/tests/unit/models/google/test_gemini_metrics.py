"""
Unit tests for Gemini metrics collection with cumulative usage.

Tests the is_cumulative_usage flag behavior for Gemini models,
verifying that cumulative token counts are correctly replaced (not accumulated).
"""

import os

import pytest

# Skip all tests if google-genai is not installed
pytest.importorskip("google.genai")

# Set test API key to avoid env var lookup errors
os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-testing")

from agno.models.base import MessageData
from agno.models.google.gemini import Gemini
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


def test_gemini_is_cumulative_usage_flag():
    """Test that Gemini has is_cumulative_usage set to True."""
    model = Gemini(id="gemini-2.0-flash")
    assert model.is_cumulative_usage is True


def test_gemini_streaming_with_cumulative_metrics():
    """
    Test that Gemini correctly handles cumulative metrics during streaming.

    Simulates 3 chunks with cumulative token counts and verifies that
    metrics are replaced (not accumulated) in each chunk.
    """
    model = Gemini(id="gemini-2.0-flash")
    stream_data = MessageData()

    # Chunk 1: Initial cumulative metrics
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=150,
            output_tokens=5,
            total_tokens=155,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    # Verify first chunk metrics
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.total_tokens == 155

    # Chunk 2: Cumulative metrics (total so far)
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=150,
            output_tokens=12,
            total_tokens=162,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # Verify metrics are replaced, not accumulated
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 12
    assert stream_data.response_metrics.total_tokens == 162

    # Chunk 3: Final cumulative metrics
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=150,
            output_tokens=25,
            total_tokens=175,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Verify final metrics reflect the cumulative total from last chunk
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 25
    assert stream_data.response_metrics.total_tokens == 175


def test_gemini_cumulative_metrics_with_cache_tokens():
    """
    Test Gemini streaming with cumulative metrics including cache tokens.

    Verifies that cache-related metrics are also correctly replaced.
    """
    model = Gemini(id="gemini-2.0-flash")
    stream_data = MessageData()

    # Chunk 1
    response_delta_1 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1000,
            output_tokens=10,
            total_tokens=1010,
            cache_read_tokens=500,
            cache_write_tokens=200,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_1))

    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 1000
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 500
    assert stream_data.response_metrics.cache_write_tokens == 200

    # Chunk 2 with updated cumulative metrics
    response_delta_2 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1000,
            output_tokens=20,
            total_tokens=1020,
            cache_read_tokens=500,
            cache_write_tokens=200,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_2))

    # All metrics should be replaced
    assert stream_data.response_metrics.input_tokens == 1000
    assert stream_data.response_metrics.output_tokens == 20
    assert stream_data.response_metrics.cache_read_tokens == 500
    assert stream_data.response_metrics.cache_write_tokens == 200

    # Chunk 3
    response_delta_3 = ModelResponse(
        response_usage=Metrics(
            input_tokens=1000,
            output_tokens=35,
            total_tokens=1035,
            cache_read_tokens=500,
            cache_write_tokens=200,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta_3))

    # Final metrics
    assert stream_data.response_metrics.input_tokens == 1000
    assert stream_data.response_metrics.output_tokens == 35
    assert stream_data.response_metrics.total_tokens == 1035
    assert stream_data.response_metrics.cache_read_tokens == 500
    assert stream_data.response_metrics.cache_write_tokens == 200


def test_gemini_empty_metrics_initialization():
    """Test that Gemini correctly initializes metrics on first chunk."""
    model = Gemini(id="gemini-2.0-flash")
    stream_data = MessageData()

    # Verify no metrics initially
    assert stream_data.response_metrics is None

    # First chunk with metrics
    response_delta = ModelResponse(
        response_usage=Metrics(
            input_tokens=100,
            output_tokens=5,
            total_tokens=105,
        )
    )
    list(model._populate_stream_data(stream_data, response_delta))

    # Metrics should be initialized
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.total_tokens == 105
