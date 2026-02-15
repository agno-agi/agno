import os

import pytest

pytest.importorskip("google.genai")

os.environ.setdefault("GOOGLE_API_KEY", "test-key-for-testing")

from agno.models.base import MessageData
from agno.models.google.gemini import Gemini
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse


def test_gemini_is_cumulative_usage_flag():
    model = Gemini(id="gemini-2.0-flash")
    assert model.is_cumulative_usage is True


def test_gemini_streaming_with_cumulative_metrics():
    model = Gemini(id="gemini-2.0-flash")
    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=150, output_tokens=5, total_tokens=155),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 5

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=150, output_tokens=12, total_tokens=162),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 12

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=150, output_tokens=25, total_tokens=175),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 150
    assert stream_data.response_metrics.output_tokens == 25
    assert stream_data.response_metrics.total_tokens == 175


def test_gemini_cumulative_metrics_with_cache_tokens():
    model = Gemini(id="gemini-2.0-flash")
    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=1000,
                    output_tokens=10,
                    total_tokens=1010,
                    cache_read_tokens=500,
                    cache_write_tokens=200,
                ),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.cache_read_tokens == 500
    assert stream_data.response_metrics.cache_write_tokens == 200

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=1000,
                    output_tokens=35,
                    total_tokens=1035,
                    cache_read_tokens=500,
                    cache_write_tokens=200,
                ),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 1000
    assert stream_data.response_metrics.output_tokens == 35
    assert stream_data.response_metrics.total_tokens == 1035
    assert stream_data.response_metrics.cache_read_tokens == 500
    assert stream_data.response_metrics.cache_write_tokens == 200


def test_gemini_empty_metrics_initialization():
    model = Gemini(id="gemini-2.0-flash")
    stream_data = MessageData()

    assert stream_data.response_metrics is None

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=100, output_tokens=5, total_tokens=105),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.total_tokens == 105
