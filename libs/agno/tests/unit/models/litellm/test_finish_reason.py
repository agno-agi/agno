from agno.models.base import MessageData
from agno.models.litellm import LiteLLM
from agno.models.response import ModelResponse


class MockChoice:
    def __init__(self, *, message=None, delta=None, finish_reason=None):
        self.message = message
        self.delta = delta
        self.finish_reason = finish_reason


class MockMessage:
    content = "final"
    reasoning_content = None
    tool_calls = None


class MockDelta:
    content = "chunk"
    reasoning_content = None
    tool_calls = None


class MockResponse:
    def __init__(self, *, finish_reason=None):
        self.choices = [MockChoice(message=MockMessage(), finish_reason=finish_reason)]
        self.usage = None


class MockChunk:
    def __init__(self, *, finish_reason=None):
        self.choices = [MockChoice(delta=MockDelta(), finish_reason=finish_reason)]
        self.usage = None


def test_litellm_non_stream_response_exposes_finish_reason_in_provider_data():
    model = LiteLLM(id="gpt-4o", api_key="test-key")

    response = model._parse_provider_response(MockResponse(finish_reason="length"))

    assert response.content == "final"
    assert response.provider_data == {"finish_reason": "length"}


def test_litellm_stream_delta_exposes_finish_reason_in_provider_data():
    model = LiteLLM(id="gpt-4o", api_key="test-key")

    response = model._parse_provider_response_delta(MockChunk(finish_reason="stop"))

    assert response.content == "chunk"
    assert response.provider_data == {"finish_reason": "stop"}


def test_provider_data_only_stream_delta_is_yielded():
    model = LiteLLM(id="gpt-4o", api_key="test-key")
    stream_data = MessageData()
    delta = ModelResponse(provider_data={"finish_reason": "length"})

    yielded = list(model._populate_stream_data(stream_data, delta))

    assert yielded == [delta]
    assert stream_data.response_provider_data == {"finish_reason": "length"}


def test_litellm_stream_delta_omits_empty_finish_reason_provider_data():
    model = LiteLLM(id="gpt-4o", api_key="test-key")

    response = model._parse_provider_response_delta(MockChunk(finish_reason=None))

    assert response.content == "chunk"
    assert response.provider_data is None
