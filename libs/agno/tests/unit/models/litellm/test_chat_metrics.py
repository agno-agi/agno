"""Unit tests for LiteLLM metrics collection."""

import pytest

pytest.importorskip("litellm")

from agno.models.litellm import LiteLLM


class MockTokenDetails:
    def __init__(self, audio_tokens=0, cached_tokens=0, reasoning_tokens=0):
        self.audio_tokens = audio_tokens
        self.cached_tokens = cached_tokens
        self.reasoning_tokens = reasoning_tokens


class MockCompletionUsage:
    def __init__(
        self,
        prompt_tokens=0,
        completion_tokens=0,
        prompt_tokens_details=None,
        completion_tokens_details=None,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.prompt_tokens_details = prompt_tokens_details
        self.completion_tokens_details = completion_tokens_details


def test_litellm_get_metrics_computes_audio_total_tokens_for_dict_usage():
    model = LiteLLM(id="test-model")
    usage = {
        "prompt_tokens": 30,
        "completion_tokens": 12,
        "prompt_tokens_details": {"audio_tokens": 4, "cached_tokens": 3},
        "completion_tokens_details": {"audio_tokens": 9, "reasoning_tokens": 2},
    }

    metrics = model._get_metrics(usage)

    assert metrics.input_tokens == 30
    assert metrics.output_tokens == 12
    assert metrics.total_tokens == 42
    assert metrics.audio_input_tokens == 4
    assert metrics.audio_output_tokens == 9
    assert metrics.audio_total_tokens == 13


def test_litellm_get_metrics_computes_audio_total_tokens_for_object_usage():
    model = LiteLLM(id="test-model")
    usage = MockCompletionUsage(
        prompt_tokens=30,
        completion_tokens=12,
        prompt_tokens_details=MockTokenDetails(audio_tokens=6, cached_tokens=1),
        completion_tokens_details=MockTokenDetails(audio_tokens=8, reasoning_tokens=5),
    )

    metrics = model._get_metrics(usage)

    assert metrics.input_tokens == 30
    assert metrics.output_tokens == 12
    assert metrics.total_tokens == 42
    assert metrics.audio_input_tokens == 6
    assert metrics.audio_output_tokens == 8
    assert metrics.audio_total_tokens == 14
