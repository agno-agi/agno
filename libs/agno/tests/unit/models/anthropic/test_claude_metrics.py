import os

import pytest

pytest.importorskip("anthropic")

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-for-testing")

from agno.models.anthropic.claude import Claude
from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


def test_claude_is_cumulative_usage_flag():
    model = Claude(id="claude-sonnet-4-5-20250929")
    assert model.is_cumulative_usage is True


def test_claude_streaming_with_cumulative_metrics():
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=200, output_tokens=8, total_tokens=208),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 200
    assert stream_data.response_metrics.output_tokens == 8
    assert stream_data.response_metrics.total_tokens == 208

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=200, output_tokens=15, total_tokens=215),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 200
    assert stream_data.response_metrics.output_tokens == 15
    assert stream_data.response_metrics.total_tokens == 215

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=200, output_tokens=30, total_tokens=230),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 200
    assert stream_data.response_metrics.output_tokens == 30
    assert stream_data.response_metrics.total_tokens == 230


def test_claude_cumulative_metrics_with_cache_tokens():
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=2000,
                    output_tokens=12,
                    total_tokens=2012,
                    cache_read_tokens=1500,
                    cache_write_tokens=300,
                ),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 2000
    assert stream_data.response_metrics.cache_read_tokens == 1500
    assert stream_data.response_metrics.cache_write_tokens == 300

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=2000,
                    output_tokens=42,
                    total_tokens=2042,
                    cache_read_tokens=1500,
                    cache_write_tokens=300,
                ),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 2000
    assert stream_data.response_metrics.output_tokens == 42
    assert stream_data.response_metrics.total_tokens == 2042
    assert stream_data.response_metrics.cache_read_tokens == 1500
    assert stream_data.response_metrics.cache_write_tokens == 300


def test_claude_extended_thinking_metrics():
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=500, output_tokens=20, total_tokens=520, reasoning_tokens=150),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.reasoning_tokens == 150

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=500, output_tokens=50, total_tokens=550, reasoning_tokens=400),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 500
    assert stream_data.response_metrics.output_tokens == 50
    assert stream_data.response_metrics.total_tokens == 550
    assert stream_data.response_metrics.reasoning_tokens == 400


def test_claude_empty_metrics_initialization():
    model = Claude(id="claude-sonnet-4-5-20250929")
    stream_data = MessageData()

    assert stream_data.response_metrics is None

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=150, output_tokens=10, total_tokens=160),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.total_tokens == 160
