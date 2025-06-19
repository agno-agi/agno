from dataclasses import dataclass
from typing import Optional, Union

from agno.models.message import MessageMetrics
from agno.utils.timer import Timer


@dataclass
class SessionMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    audio_tokens: int = 0
    input_audio_tokens: int = 0
    output_audio_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens_details: Optional[dict] = None
    completion_tokens_details: Optional[dict] = None

    additional_metrics: Optional[dict] = None

    time: Optional[float] = None
    time_to_first_token: Optional[float] = None

    timer: Optional[Timer] = None

    def start_timer(self):
        if self.timer is None:
            self.timer = Timer()
        self.timer.start()

    def stop_timer(self, set_time: bool = True):
        if self.timer is not None:
            self.timer.stop()
            if set_time:
                self.time = self.timer.elapsed

    def set_time_to_first_token(self):
        if self.timer is not None:
            self.time_to_first_token = self.timer.elapsed

    def __add__(self, other: Union["SessionMetrics", "MessageMetrics"]) -> "SessionMetrics":
        # Create new instance with summed basic metrics
        result = SessionMetrics(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            audio_tokens=self.audio_tokens + other.audio_tokens,
            input_audio_tokens=self.input_audio_tokens + other.input_audio_tokens,
            output_audio_tokens=self.output_audio_tokens + other.output_audio_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )

        # Handle prompt_tokens_details
        if self.prompt_tokens_details or other.prompt_tokens_details:
            result.prompt_tokens_details = {}
            # Merge from self
            if self.prompt_tokens_details:
                result.prompt_tokens_details.update(self.prompt_tokens_details)
            # Add values from other
            if other.prompt_tokens_details:
                for key, value in other.prompt_tokens_details.items():
                    result.prompt_tokens_details[key] = result.prompt_tokens_details.get(key, 0) + value

        # Handle completion_tokens_details similarly
        if self.completion_tokens_details or other.completion_tokens_details:
            result.completion_tokens_details = {}
            if self.completion_tokens_details:
                result.completion_tokens_details.update(self.completion_tokens_details)
            if other.completion_tokens_details:
                for key, value in other.completion_tokens_details.items():
                    result.completion_tokens_details[key] = result.completion_tokens_details.get(key, 0) + value

        # Handle additional metrics
        if self.additional_metrics or other.additional_metrics:
            result.additional_metrics = {}
            if self.additional_metrics:
                result.additional_metrics.update(self.additional_metrics)
            if other.additional_metrics:
                result.additional_metrics.update(other.additional_metrics)

        # Sum times if both exist
        if self.time is not None and other.time is not None:
            result.time = self.time + other.time
        elif self.time is not None:
            result.time = self.time
        elif other.time is not None:
            result.time = other.time

        # Handle time_to_first_token (take the first non-None value)
        result.time_to_first_token = self.time_to_first_token or other.time_to_first_token

        return result

    def __radd__(self, other: Union["SessionMetrics", "MessageMetrics"]) -> "SessionMetrics":
        if other == 0:  # Handle sum() starting value
            return self
        return self + other
