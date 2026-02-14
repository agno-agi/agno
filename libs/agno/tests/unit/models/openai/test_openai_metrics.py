from typing import Optional

from agno.models.base import MessageData
from agno.models.metrics import Metrics
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse


class MockCompletionUsage:
    def __init__(
        self,
        prompt_tokens: Optional[int] = 0,
        completion_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
        prompt_tokens_details=None,
        completion_tokens_details=None,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens_details = prompt_tokens_details
        self.completion_tokens_details = completion_tokens_details


def test_openai_is_cumulative_usage_flag():
    model = OpenAIChat(id="gpt-4o")
    assert model.is_cumulative_usage is False


def test_openai_get_metrics_basic():
    model = OpenAIChat(id="gpt-4o")
    usage = MockCompletionUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert isinstance(metrics, Metrics)
    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 20
    assert metrics.total_tokens == 120


def test_openai_get_metrics_with_details():
    model = OpenAIChat(id="gpt-4o")

    class MockPromptTokensDetails:
        def __init__(self):
            self.audio_tokens = 10
            self.cached_tokens = 500

    class MockCompletionTokensDetails:
        def __init__(self):
            self.audio_tokens = 5
            self.reasoning_tokens = 100

    usage = MockCompletionUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_tokens_details=MockPromptTokensDetails(),
        completion_tokens_details=MockCompletionTokensDetails(),
    )

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 20
    assert metrics.total_tokens == 120
    assert metrics.audio_input_tokens == 10
    assert metrics.cache_read_tokens == 500
    assert metrics.audio_output_tokens == 5
    assert metrics.reasoning_tokens == 100


def test_openai_streaming_metrics_simulation():
    model = OpenAIChat(id="gpt-4o")
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
                response_usage=Metrics(input_tokens=0, output_tokens=1, total_tokens=1),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 2

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(input_tokens=0, output_tokens=1, total_tokens=1),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 3
    assert stream_data.response_metrics.total_tokens == 103


def test_openai_get_metrics_with_none_values():
    model = OpenAIChat(id="gpt-4o")
    usage = MockCompletionUsage(prompt_tokens=None, completion_tokens=None, total_tokens=None)

    metrics = model._get_metrics(usage)  # type: ignore[arg-type]

    assert metrics.input_tokens == 0
    assert metrics.output_tokens == 0
    assert metrics.total_tokens == 0


def test_openai_incremental_usage_with_detailed_metrics():
    model = OpenAIChat(id="gpt-4o")
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
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.reasoning_tokens == 10
    assert stream_data.response_metrics.cache_read_tokens == 50

    list(
        model._populate_stream_data(
            stream_data,
            ModelResponse(
                response_usage=Metrics(
                    input_tokens=0,
                    output_tokens=5,
                    total_tokens=5,
                    reasoning_tokens=10,
                    cache_read_tokens=0,
                ),
            ),
        )
    )
    assert stream_data.response_metrics.input_tokens == 100
    assert stream_data.response_metrics.output_tokens == 10
    assert stream_data.response_metrics.reasoning_tokens == 20
    assert stream_data.response_metrics.cache_read_tokens == 50
