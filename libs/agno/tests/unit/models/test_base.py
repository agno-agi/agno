from typing import Any, Dict, Optional

from agno.models.base import _add_usage_metrics_to_assistant_message
from agno.models.message import Message


class _FakeInputTokensDetails:
    """Mock object for input_tokens_details with cached_tokens."""

    def __init__(self, cached_tokens: Optional[int] = None):
        self.cached_tokens = cached_tokens

    def model_dump(self, exclude_none: bool = True) -> Dict[str, Any]:
        result = {"cached_tokens": self.cached_tokens}
        if exclude_none and self.cached_tokens is None:
            result.pop("cached_tokens")
        return result


class _FakeOutputTokensDetails:
    """Mock object for output_tokens_details with reasoning_tokens."""

    def __init__(self, reasoning_tokens: Optional[int] = None):
        self.reasoning_tokens = reasoning_tokens

    def model_dump(self, exclude_none: bool = True) -> Dict[str, Any]:
        result = {"reasoning_tokens": self.reasoning_tokens}
        if exclude_none and self.reasoning_tokens is None:
            result.pop("reasoning_tokens")
        return result


class _FakePromptTokensDetails:
    """Mock object for legacy prompt_tokens_details with cached_tokens."""

    def __init__(self, cached_tokens: Optional[int] = None, audio_tokens: Optional[int] = None):
        self.cached_tokens = cached_tokens
        self.audio_tokens = audio_tokens

    def model_dump(self, exclude_none: bool = True) -> Dict[str, Any]:
        result = {"cached_tokens": self.cached_tokens, "audio_tokens": self.audio_tokens}
        if exclude_none:
            result = {k: v for k, v in result.items() if v is not None}
        return result


class _FakeCompletionTokensDetails:
    """Mock object for legacy completion_tokens_details with reasoning_tokens."""

    def __init__(self, reasoning_tokens: Optional[int] = None, audio_tokens: Optional[int] = None):
        self.reasoning_tokens = reasoning_tokens
        self.audio_tokens = audio_tokens

    def model_dump(self, exclude_none: bool = True) -> Dict[str, Any]:
        result = {"reasoning_tokens": self.reasoning_tokens, "audio_tokens": self.audio_tokens}
        if exclude_none:
            result = {k: v for k, v in result.items() if v is not None}
        return result


class _FakeResponseUsage:
    """Mock response usage object with both new and legacy format support."""

    def __init__(
        self,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        cached_tokens: Optional[int] = None,
        cache_write_tokens: Optional[int] = None,
        input_tokens_details: Optional[_FakeInputTokensDetails] = None,
        output_tokens_details: Optional[_FakeOutputTokensDetails] = None,
        prompt_tokens_details: Optional[_FakePromptTokensDetails] = None,
        completion_tokens_details: Optional[_FakeCompletionTokensDetails] = None,
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.cached_tokens = cached_tokens
        self.cache_write_tokens = cache_write_tokens
        self.input_tokens_details = input_tokens_details
        self.output_tokens_details = output_tokens_details
        self.prompt_tokens_details = prompt_tokens_details
        self.completion_tokens_details = completion_tokens_details


def test_output_tokens_details_object_format():
    """Test extraction of reasoning_tokens from output_tokens_details object format."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100, output_tokens=50, output_tokens_details=_FakeOutputTokensDetails(reasoning_tokens=15)
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.reasoning_tokens == 15


def test_both_details_fields_together():
    """Test both input_tokens_details and output_tokens_details together."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100,
        output_tokens=50,
        input_tokens_details=_FakeInputTokensDetails(cached_tokens=25),
        output_tokens_details=_FakeOutputTokensDetails(reasoning_tokens=15),
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.cached_tokens == 25
    assert assistant_message.metrics.reasoning_tokens == 15


def test_legacy_prompt_tokens_details_object_format():
    """Test backward compatibility with prompt_tokens_details object format."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100,
        output_tokens=50,
        prompt_tokens_details=_FakePromptTokensDetails(cached_tokens=25, audio_tokens=5),
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.cached_tokens == 25
    assert assistant_message.metrics.input_audio_tokens == 5


def test_legacy_completion_tokens_details_object_format():
    """Test backward compatibility with completion_tokens_details object format."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100,
        output_tokens=50,
        completion_tokens_details=_FakeCompletionTokensDetails(reasoning_tokens=15, audio_tokens=3),
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.reasoning_tokens == 15
    assert assistant_message.metrics.output_audio_tokens == 3


def test_legacy_prompt_tokens_details_dict_format():
    """Test backward compatibility with prompt_tokens_details dict format."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(input_tokens=100, output_tokens=50)
    response_usage.prompt_tokens_details = {"cached_tokens": 25, "audio_tokens": 5}

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.cached_tokens == 25
    assert assistant_message.metrics.input_audio_tokens == 5


def test_legacy_completion_tokens_details_dict_format():
    """Test backward compatibility with completion_tokens_details dict format."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(input_tokens=100, output_tokens=50)
    response_usage.completion_tokens_details = {"reasoning_tokens": 15, "audio_tokens": 3}

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.reasoning_tokens == 15
    assert assistant_message.metrics.output_audio_tokens == 3


def test_standard_dict_usage():
    """Test basic dict format with standard fields."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "cached_tokens": 25}

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.total_tokens == 150
    assert assistant_message.metrics.cached_tokens == 25


def test_standard_object_usage():
    """Test basic object format with standard fields."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100, output_tokens=50, total_tokens=150, cached_tokens=25, cache_write_tokens=10
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.total_tokens == 150
    assert assistant_message.metrics.cached_tokens == 25
    assert assistant_message.metrics.cache_write_tokens == 10


def test_total_tokens_calculation():
    """Test auto-calculation of total_tokens when missing."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = {"input_tokens": 100, "output_tokens": 50}

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.total_tokens == 150  # Auto-calculated


def test_none_values_handling():
    """Test that None values don't cause errors and are handled gracefully."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100,
        output_tokens=50,
        input_tokens_details=_FakeInputTokensDetails(cached_tokens=None),
        output_tokens_details=_FakeOutputTokensDetails(reasoning_tokens=None),
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    # cached_tokens and reasoning_tokens should remain at default (0)
    assert assistant_message.metrics.cached_tokens == 0
    assert assistant_message.metrics.reasoning_tokens == 0


def test_priority_new_over_legacy_cached_tokens():
    """Test that input_tokens_details.cached_tokens takes priority over prompt_tokens_details.cached_tokens."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100,
        output_tokens=50,
        input_tokens_details=_FakeInputTokensDetails(cached_tokens=30),  # New format - should win
        prompt_tokens_details=_FakePromptTokensDetails(cached_tokens=20),  # Legacy format
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.cached_tokens == 30  # Should use new format value


def test_priority_new_over_legacy_reasoning_tokens():
    """Test that output_tokens_details.reasoning_tokens takes priority over completion_tokens_details.reasoning_tokens."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = _FakeResponseUsage(
        input_tokens=100,
        output_tokens=50,
        output_tokens_details=_FakeOutputTokensDetails(reasoning_tokens=20),  # New format - should win
        completion_tokens_details=_FakeCompletionTokensDetails(reasoning_tokens=10),  # Legacy format
    )

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    assert assistant_message.metrics.input_tokens == 100
    assert assistant_message.metrics.output_tokens == 50
    assert assistant_message.metrics.reasoning_tokens == 20  # Should use new format value


def test_empty_response_usage():
    """Test handling of empty or minimal response objects."""
    assistant_message = Message(role="assistant", content="test")

    response_usage = {}

    _add_usage_metrics_to_assistant_message(assistant_message, response_usage)

    # Should set defaults without errors
    assert assistant_message.metrics.input_tokens == 0
    assert assistant_message.metrics.output_tokens == 0
    assert assistant_message.metrics.total_tokens == 0
    assert assistant_message.metrics.cached_tokens == 0
    assert assistant_message.metrics.reasoning_tokens == 0
