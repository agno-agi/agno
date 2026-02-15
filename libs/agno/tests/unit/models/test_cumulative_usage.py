import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse


def test_accumulate_metrics_when_is_cumulative_usage_false():
    model = OpenAIChat(id="gpt-4o")
    assert model.is_cumulative_usage is False

    stream_data = MessageData()

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

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=0, output_tokens=3, total_tokens=3),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 8
    assert stream_data.response_metrics.total_tokens == 108

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=0, output_tokens=2, total_tokens=2),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.total_tokens == 110


def test_replace_metrics_when_is_cumulative_usage_true():
    model = OpenAIChat(id="gpt-4o")
    model.is_cumulative_usage = True

    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=100, output_tokens=1, total_tokens=101),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 1

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=100, output_tokens=2, total_tokens=102),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 2
    assert stream_data.response_metrics.total_tokens == 102

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=100, output_tokens=5, total_tokens=105),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 5
    assert stream_data.response_metrics.total_tokens == 105


def test_cumulative_usage_with_detailed_metrics():
    model = OpenAIChat(id="gpt-4o")
    model.is_cumulative_usage = True

    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=100,
                    output_tokens=5,
                    total_tokens=105,
                    reasoning_tokens=10,
                    cache_read_tokens=50,
                ),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.reasoning_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 50

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=100,
                    output_tokens=10,
                    total_tokens=110,
                    reasoning_tokens=20,
                    cache_read_tokens=50,
                ),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.reasoning_tokens == 20
    assert stream_data.response_metrics.cache_read_tokens == 50


def test_accumulate_usage_with_detailed_metrics():
    model = OpenAIChat(id="gpt-4o")
    assert model.is_cumulative_usage is False

    stream_data = MessageData()

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=100,
                    output_tokens=5,
                    total_tokens=105,
                    reasoning_tokens=10,
                    cache_read_tokens=50,
                ),
            ),
        )
    )
    assert stream_data.response_metrics is not None
    assert stream_data.response_metrics.reasoning_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 50

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=0,
                    output_tokens=3,
                    total_tokens=3,
                    reasoning_tokens=5,
                    cache_read_tokens=0,
                ),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 8
    assert stream_data.response_metrics.reasoning_tokens == 15
    assert stream_data.response_metrics.cache_read_tokens == 50
