from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from agno.utils.timer import Timer


@dataclass
class Metrics:
    """All relevant metrics for a session, run or message."""

    # Main token consumption values
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # Audio token usage
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0
    audio_total_tokens: int = 0

    # Cache token usage
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    # Tokens employed in reasoning
    reasoning_tokens: int = 0

    # Time metrics
    # Internal timer utility for tracking execution time
    timer: Optional[Timer] = None
    # Time from run start to first token generation, in seconds
    time_to_first_token: Optional[float] = None
    # Total run time, in seconds
    duration: Optional[float] = None

    # Provider-specific metrics
    provider_metrics: Optional[dict] = None

    # Any additional metrics
    additional_metrics: Optional[dict] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove the timer util if present
        metrics_dict.pop("timer", None)
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }
        return metrics_dict

    def __add__(self, other: "Metrics") -> "Metrics":
        # Create new instance of the same type as self
        result_class = type(self)
        result = result_class(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            audio_total_tokens=self.audio_total_tokens + other.audio_total_tokens,
            audio_input_tokens=self.audio_input_tokens + other.audio_input_tokens,
            audio_output_tokens=self.audio_output_tokens + other.audio_output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )

        # Handle provider_metrics
        if self.provider_metrics or other.provider_metrics:
            result.provider_metrics = {}
            if self.provider_metrics:
                result.provider_metrics.update(self.provider_metrics)
            if other.provider_metrics:
                result.provider_metrics.update(other.provider_metrics)

        # Handle additional metrics
        if self.additional_metrics or other.additional_metrics:
            result.additional_metrics = {}
            if self.additional_metrics:
                result.additional_metrics.update(self.additional_metrics)
            if other.additional_metrics:
                result.additional_metrics.update(other.additional_metrics)

        # Sum durations if both exist
        if self.duration is not None and other.duration is not None:
            result.duration = self.duration + other.duration
        elif self.duration is not None:
            result.duration = self.duration
        elif other.duration is not None:
            result.duration = other.duration

        # Sum time to first token if both exist
        if self.time_to_first_token is not None and other.time_to_first_token is not None:
            result.time_to_first_token = self.time_to_first_token + other.time_to_first_token
        elif self.time_to_first_token is not None:
            result.time_to_first_token = self.time_to_first_token
        elif other.time_to_first_token is not None:
            result.time_to_first_token = other.time_to_first_token

        return result

    def __radd__(self, other: "Metrics") -> "Metrics":
        if other == 0:  # Handle sum() starting value
            return self
        return self + other

    def start_timer(self):
        if self.timer is None:
            self.timer = Timer()
        self.timer.start()

    def stop_timer(self, set_duration: bool = True):
        if self.timer is not None:
            self.timer.stop()
            if set_duration:
                self.duration = self.timer.elapsed

    def set_time_to_first_token(self):
        if self.timer is not None:
            self.time_to_first_token = self.timer.elapsed
