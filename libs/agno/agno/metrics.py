from dataclasses import asdict, dataclass
from time import time
from typing import Any, Dict, List, Optional, Tuple

from agno.utils.timer import Timer


@dataclass
class ModelMetrics:
    """Metrics for a specific model instance - used in Metrics.details."""

    id: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    time_to_first_token: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Only include valid fields (filter out any old fields like provider_metrics, additional_metrics)
        valid_fields = {"id", "provider", "input_tokens", "output_tokens", "total_tokens", "time_to_first_token"}
        metrics_dict = {k: v for k, v in metrics_dict.items() if k in valid_fields}
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }
        return metrics_dict


@dataclass
class ToolCallMetrics:
    """Metrics for tool execution - only time-related fields."""

    # Time metrics
    # Internal timer utility for tracking execution time
    timer: Optional[Timer] = None
    # Tool execution start time (Unix timestamp)
    start_time: Optional[float] = None
    # Tool execution end time (Unix timestamp)
    end_time: Optional[float] = None
    # Total tool execution time, in seconds
    duration: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove the timer util if present
        metrics_dict.pop("timer", None)
        metrics_dict = {
            k: v for k, v in metrics_dict.items() if v is not None and (not isinstance(v, (int, float)) or v != 0)
        }
        return metrics_dict

    def start_timer(self):
        """Start the timer and record start time."""
        if self.timer is None:
            self.timer = Timer()
        self.timer.start()
        if self.start_time is None:
            self.start_time = time()

    def stop_timer(self, set_duration: bool = True):
        """Stop the timer and record end time."""
        if self.timer is not None:
            self.timer.stop()
            if set_duration:
                self.duration = self.timer.elapsed
        if self.end_time is None:
            self.end_time = time()


@dataclass
class MessageMetrics:
    """Metrics for individual messages - token consumption and message-level timing.
    Only set on assistant messages from model responses."""

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
    # Time from message start to first token generation, in seconds
    time_to_first_token: Optional[float] = None

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

    def __add__(self, other: "MessageMetrics") -> "MessageMetrics":
        """Sum two MessageMetrics objects."""
        result = MessageMetrics(
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

        # Preserve timer from self (left operand)
        result.timer = self.timer

        # Sum time to first token if both exist
        if self.time_to_first_token is not None and other.time_to_first_token is not None:
            result.time_to_first_token = self.time_to_first_token + other.time_to_first_token
        elif self.time_to_first_token is not None:
            result.time_to_first_token = self.time_to_first_token
        elif other.time_to_first_token is not None:
            result.time_to_first_token = other.time_to_first_token

        return result

    def start_timer(self):
        """Start the timer for message processing."""
        if self.timer is None:
            self.timer = Timer()
        self.timer.start()

    def stop_timer(self, set_duration: bool = True):
        """Stop the timer."""
        if self.timer is not None:
            self.timer.stop()

    def set_time_to_first_token(self):
        """Set time to first token from the timer."""
        if self.timer is not None:
            self.time_to_first_token = self.timer.elapsed


@dataclass
class SessionModelMetrics:
    """Metrics for a specific model instance aggregated across a session."""

    id: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # Average duration across all runs using this model, in seconds
    average_duration: Optional[float] = None
    # Total number of runs that used this model
    total_runs: int = 0

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Only include valid fields
        valid_fields = {
            "id",
            "provider",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "average_duration",
            "total_runs",
        }
        metrics_dict = {k: v for k, v in metrics_dict.items() if k in valid_fields}
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }
        return metrics_dict


@dataclass
class SessionMetrics:
    """Metrics for a session - aggregated token metrics from all runs.
    Excludes run-level timing fields like duration and time_to_first_token."""

    # Main token consumption values (aggregated from all runs)
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

    # Session-level aggregated stats
    # Average duration across all runs, in seconds
    average_duration: Optional[float] = None
    # Total number of runs in this session
    total_runs: int = 0

    # Per-model metrics breakdown across the session
    # List of SessionModelMetrics, one per unique (provider, id) combination
    details: Optional[List[SessionModelMetrics]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Convert details SessionModelMetrics to dicts
        if metrics_dict.get("details") is not None:
            details_list = [
                m.to_dict()
                if isinstance(m, SessionModelMetrics)
                else {
                    k: v
                    for k, v in m.items()
                    if k
                    in {
                        "id",
                        "provider",
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "average_duration",
                        "total_runs",
                    }
                    and v is not None
                }
                for m in metrics_dict["details"]
            ]
            metrics_dict["details"] = details_list
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None
            and (not isinstance(v, (int, float)) or v != 0)
            and (not isinstance(v, (dict, list)) or len(v) > 0)
        }
        return metrics_dict

    def __add__(self, other: "SessionMetrics") -> "SessionMetrics":
        """Sum two SessionMetrics objects."""
        total_runs = self.total_runs + other.total_runs

        # Calculate average duration
        average_duration = None
        if self.average_duration is not None and other.average_duration is not None:
            # Weighted average
            total_duration = (self.average_duration * self.total_runs) + (other.average_duration * other.total_runs)
            average_duration = total_duration / total_runs if total_runs > 0 else None
        elif self.average_duration is not None:
            average_duration = self.average_duration
        elif other.average_duration is not None:
            average_duration = other.average_duration

        # Merge details lists by (provider, id) combination
        merged_details: Optional[List[SessionModelMetrics]] = None
        if self.details or other.details:
            merged_details = []
            # Create a dict keyed by (provider, id) for efficient lookup
            details_dict: Dict[Tuple[str, str], SessionModelMetrics] = {}

            # Add self.details
            if self.details:
                for model_metrics in self.details:
                    key = (model_metrics.provider, model_metrics.id)
                    if key not in details_dict:
                        details_dict[key] = SessionModelMetrics(
                            id=model_metrics.id,
                            provider=model_metrics.provider,
                            input_tokens=model_metrics.input_tokens,
                            output_tokens=model_metrics.output_tokens,
                            total_tokens=model_metrics.total_tokens,
                            average_duration=model_metrics.average_duration,
                            total_runs=model_metrics.total_runs,
                        )
                    else:
                        existing = details_dict[key]
                        existing.input_tokens += model_metrics.input_tokens
                        existing.output_tokens += model_metrics.output_tokens
                        existing.total_tokens += model_metrics.total_tokens
                        existing.total_runs += model_metrics.total_runs
                        # Calculate weighted average duration
                        if model_metrics.average_duration is not None:
                            if existing.average_duration is None:
                                existing.average_duration = model_metrics.average_duration
                            else:
                                total_duration = (existing.average_duration * existing.total_runs) + (
                                    model_metrics.average_duration * model_metrics.total_runs
                                )
                                existing.average_duration = (
                                    total_duration / existing.total_runs if existing.total_runs > 0 else None
                                )

            # Add other.details
            if other.details:
                for model_metrics in other.details:
                    key = (model_metrics.provider, model_metrics.id)
                    if key not in details_dict:
                        details_dict[key] = SessionModelMetrics(
                            id=model_metrics.id,
                            provider=model_metrics.provider,
                            input_tokens=model_metrics.input_tokens,
                            output_tokens=model_metrics.output_tokens,
                            total_tokens=model_metrics.total_tokens,
                            average_duration=model_metrics.average_duration,
                            total_runs=model_metrics.total_runs,
                        )
                    else:
                        existing = details_dict[key]
                        existing.input_tokens += model_metrics.input_tokens
                        existing.output_tokens += model_metrics.output_tokens
                        existing.total_tokens += model_metrics.total_tokens
                        existing.total_runs += model_metrics.total_runs
                        # Calculate weighted average duration
                        if model_metrics.average_duration is not None:
                            if existing.average_duration is None:
                                existing.average_duration = model_metrics.average_duration
                            else:
                                total_duration = (existing.average_duration * existing.total_runs) + (
                                    model_metrics.average_duration * model_metrics.total_runs
                                )
                                existing.average_duration = (
                                    total_duration / existing.total_runs if existing.total_runs > 0 else None
                                )

            merged_details = list(details_dict.values())

        result = SessionMetrics(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            audio_total_tokens=self.audio_total_tokens + other.audio_total_tokens,
            audio_input_tokens=self.audio_input_tokens + other.audio_input_tokens,
            audio_output_tokens=self.audio_output_tokens + other.audio_output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            average_duration=average_duration,
            total_runs=total_runs,
            details=merged_details,
        )

        return result


@dataclass
class Metrics:
    """Metrics for a run - aggregated token metrics from messages plus run-level timing.
    Used by RunOutput.metrics."""

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

    # Per-model metrics breakdown
    # Keys: "model", "output_model", etc. (only includes model types that were used)
    # Values: List of ModelMetrics (for future fallback models support)
    details: Optional[Dict[str, List[ModelMetrics]]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove the timer util if present
        metrics_dict.pop("timer", None)
        # Remove any old fields that no longer exist in the dataclass (e.g., from deserialized old data)
        valid_fields = {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "audio_input_tokens",
            "audio_output_tokens",
            "audio_total_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "time_to_first_token",
            "duration",
            "details",
        }
        metrics_dict = {k: v for k, v in metrics_dict.items() if k in valid_fields}
        # Convert details ModelMetrics to dicts
        if metrics_dict.get("details") is not None:
            details_dict = {}
            valid_model_metrics_fields = {
                "id",
                "provider",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "time_to_first_token",
            }
            for model_type, model_metrics_list in metrics_dict["details"].items():
                details_dict[model_type] = [
                    m.to_dict()
                    if isinstance(m, ModelMetrics)
                    else {k: v for k, v in m.items() if k in valid_model_metrics_fields and v is not None}
                    for m in model_metrics_list
                ]
            metrics_dict["details"] = details_dict
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

        # Merge details dictionaries
        if self.details or other.details:
            result.details = {}
            if self.details:
                result.details.update(self.details)
            if other.details:
                # Merge lists for same model types
                for model_type, model_metrics_list in other.details.items():
                    if model_type in result.details:
                        result.details[model_type].extend(model_metrics_list)
                    else:
                        result.details[model_type] = model_metrics_list.copy()

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
