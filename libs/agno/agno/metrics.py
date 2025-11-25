from dataclasses import asdict, dataclass
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from agno.utils.timer import Timer

if TYPE_CHECKING:
    from agno.models.base import Model
    from agno.models.response import ModelResponse
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


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
        # Only include valid fields (filter out any old deprecated fields like additional_metrics)
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCallMetrics":
        """Create ToolCallMetrics from dict, handling ISO format strings for start_time and end_time."""
        from datetime import datetime

        metrics_data = data.copy()

        # Convert ISO format strings back to Unix timestamps if needed
        if "start_time" in metrics_data and isinstance(metrics_data["start_time"], str):
            try:
                metrics_data["start_time"] = datetime.fromisoformat(metrics_data["start_time"]).timestamp()
            except (ValueError, AttributeError):
                # If parsing fails, try as float (backward compatibility)
                try:
                    metrics_data["start_time"] = float(metrics_data["start_time"])
                except (ValueError, TypeError):
                    metrics_data["start_time"] = None

        if "end_time" in metrics_data and isinstance(metrics_data["end_time"], str):
            try:
                metrics_data["end_time"] = datetime.fromisoformat(metrics_data["end_time"]).timestamp()
            except (ValueError, AttributeError):
                # If parsing fails, try as float (backward compatibility)
                try:
                    metrics_data["end_time"] = float(metrics_data["end_time"])
                except (ValueError, TypeError):
                    metrics_data["end_time"] = None

        return cls(**metrics_data)


@dataclass
class MessageMetrics:
    """Metrics for individual messages - token consumption and message-level timing.
    Only set on assistant messages from model responses."""

    # We should make these NONE instead of 0. then on _add, check for None and add 0 if None

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
    provider_metrics: Optional[Dict[str, Any]] = None

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

        # Merge provider_metrics dictionaries
        if self.provider_metrics is not None or other.provider_metrics is not None:
            result.provider_metrics = {}
            if self.provider_metrics:
                result.provider_metrics.update(self.provider_metrics)
            if other.provider_metrics:
                result.provider_metrics.update(other.provider_metrics)

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

    @classmethod
    def from_metrics(cls, metrics: "RunMetrics") -> "MessageMetrics":
        """Create MessageMetrics from a RunMetrics object (e.g., from provider response usage).

        Args:
            metrics: A RunMetrics object containing token usage information

        Returns:
            A new MessageMetrics instance with token fields copied from the RunMetrics object
        """
        return cls(
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            total_tokens=metrics.total_tokens,
            audio_input_tokens=metrics.audio_input_tokens,
            audio_output_tokens=metrics.audio_output_tokens,
            audio_total_tokens=metrics.audio_total_tokens,
            cache_read_tokens=metrics.cache_read_tokens,
            cache_write_tokens=metrics.cache_write_tokens,
            reasoning_tokens=metrics.reasoning_tokens,
            provider_metrics=getattr(metrics, "provider_metrics", None),
        )


@dataclass
class SessionModelMetrics(ModelMetrics):
    """Metrics for a specific model instance aggregated across a session."""

    # Average duration across all runs using this model, in seconds
    average_duration: Optional[float] = None
    # Total number of runs that used this model
    total_runs: int = 0

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Only include valid fields (from parent ModelMetrics + session-specific fields)
        valid_fields = {
            "id",
            "provider",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "time_to_first_token",
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
class RunMetrics:
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

    # Provider-specific metrics (e.g., Anthropic's server_tool_use, service_tier)
    provider_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove the timer util if present
        metrics_dict.pop("timer", None)
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
            "provider_metrics",
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

    def __add__(self, other: "RunMetrics") -> "RunMetrics":
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

    def __radd__(self, other: "RunMetrics") -> "RunMetrics":
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


@dataclass
class SessionMetrics(RunMetrics):
    """Metrics for a session - aggregated token metrics from all runs.
    Excludes run-level timing fields like duration and time_to_first_token."""

    # Override run-level timing fields - exclude them for session metrics
    timer: Optional[Timer] = None  # type: ignore[assignment]
    time_to_first_token: Optional[float] = None  # type: ignore[assignment]
    duration: Optional[float] = None  # type: ignore[assignment]

    # Session-level aggregated stats
    # Average duration across all runs, in seconds
    average_duration: Optional[float] = None
    # Total number of runs in this session
    total_runs: int = 0

    # Override details field - session uses List[SessionModelMetrics] instead of Dict[str, List[ModelMetrics]]
    details: Optional[List[SessionModelMetrics]] = None  # type: ignore[assignment]

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove run-level timing fields (excluded from session metrics)
        metrics_dict.pop("timer", None)
        metrics_dict.pop("time_to_first_token", None)
        metrics_dict.pop("duration", None)
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


def accumulate_model_metrics(
    model_response: "ModelResponse",
    model: "Model",
    model_type: str,
    run_response: "Union[RunOutput, TeamRunOutput]",
) -> None:
    """Accumulate metrics from a model response into run_response.metrics.

    This is a standalone function that can be used by managers and other components
    that don't have direct access to Agent instances.

    Args:
        model_response: The ModelResponse containing response_usage metrics
        model: The Model instance that generated the response
        model_type: Type identifier ("model", "output_model", "reasoning_model", etc.)
        run_response: The RunOutput to accumulate metrics into
    """

    # If response_usage is None, return early (no metrics to accumulate)
    if model_response.response_usage is None:
        return

    usage = model_response.response_usage

    # Initialize run_response.metrics if None
    if run_response.metrics is None:
        run_response.metrics = RunMetrics()
        run_response.metrics.start_timer()

    # Initialize details dict if None
    if run_response.metrics.details is None:
        run_response.metrics.details = {}

    # Get model info
    model_id = model.id
    model_provider = model.get_provider()

    # Create ModelMetrics entry
    model_metrics = ModelMetrics(
        id=model_id,
        provider=model_provider,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        total_tokens=usage.total_tokens or 0,
        time_to_first_token=usage.time_to_first_token,
    )

    # Add to details dict (create list if needed)
    if model_type not in run_response.metrics.details:
        run_response.metrics.details[model_type] = []
    run_response.metrics.details[model_type].append(model_metrics)

    # Accumulate token counts to top-level metrics
    run_response.metrics.input_tokens += usage.input_tokens or 0
    run_response.metrics.output_tokens += usage.output_tokens or 0
    run_response.metrics.total_tokens += usage.total_tokens or 0
    run_response.metrics.audio_input_tokens += usage.audio_input_tokens or 0
    run_response.metrics.audio_output_tokens += usage.audio_output_tokens or 0
    run_response.metrics.audio_total_tokens += usage.audio_total_tokens or 0
    run_response.metrics.cache_read_tokens += usage.cache_read_tokens or 0
    run_response.metrics.cache_write_tokens += usage.cache_write_tokens or 0
    run_response.metrics.reasoning_tokens += usage.reasoning_tokens or 0

    # Handle time_to_first_token: only set top-level if model_type is "model" or "reasoning_model"
    # and current value is None or later (we want the earliest)
    if model_type in ("model", "reasoning_model") and usage.time_to_first_token is not None:
        if run_response.metrics.time_to_first_token is None:
            run_response.metrics.time_to_first_token = usage.time_to_first_token
        elif usage.time_to_first_token < run_response.metrics.time_to_first_token:
            run_response.metrics.time_to_first_token = usage.time_to_first_token

    # Merge provider_metrics if present
    if usage.provider_metrics is not None:
        if run_response.metrics.provider_metrics is None:
            run_response.metrics.provider_metrics = {}
        run_response.metrics.provider_metrics.update(usage.provider_metrics)
