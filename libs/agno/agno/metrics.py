from dataclasses import asdict, dataclass
from dataclasses import fields as dc_fields
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
    """Metrics for a specific model instance.

    Used in Metrics.details (run-level, per-model breakdown) and
    SessionMetrics.details (session-level, aggregated across runs).

    When used at session level, average_duration and total_runs are populated.
    """

    id: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0
    audio_total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    time_to_first_token: Optional[float] = None
    cost: Optional[float] = None
    provider_metrics: Optional[Dict[str, Any]] = None
    # Session aggregation fields (only populated in session context)
    average_duration: Optional[float] = None
    total_runs: int = 0

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove any None, 0, or empty dict values
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }
        return metrics_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelMetrics":
        valid = {f.name for f in dc_fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    @classmethod
    def for_session(cls, model_metric: "ModelMetrics", duration: Optional[float] = None, total_runs: int = 1) -> "ModelMetrics":
        """Create a ModelMetrics with session aggregation fields populated."""
        return cls(
            id=model_metric.id,
            provider=model_metric.provider,
            input_tokens=model_metric.input_tokens,
            output_tokens=model_metric.output_tokens,
            total_tokens=model_metric.total_tokens,
            audio_input_tokens=model_metric.audio_input_tokens,
            audio_output_tokens=model_metric.audio_output_tokens,
            audio_total_tokens=model_metric.audio_total_tokens,
            cache_read_tokens=model_metric.cache_read_tokens,
            cache_write_tokens=model_metric.cache_write_tokens,
            reasoning_tokens=model_metric.reasoning_tokens,
            cost=model_metric.cost,
            average_duration=duration,
            total_runs=total_runs,
        )

    # Backward compatibility alias
    from_model_metrics = for_session

    def accumulate(self, other: "ModelMetrics") -> None:
        """Accumulate token counts from another ModelMetrics into this one."""
        self.input_tokens += other.input_tokens or 0
        self.output_tokens += other.output_tokens or 0
        self.total_tokens += other.total_tokens or 0
        self.audio_input_tokens += other.audio_input_tokens or 0
        self.audio_output_tokens += other.audio_output_tokens or 0
        self.audio_total_tokens += other.audio_total_tokens or 0
        self.cache_read_tokens += other.cache_read_tokens or 0
        self.cache_write_tokens += other.cache_write_tokens or 0
        self.reasoning_tokens += other.reasoning_tokens or 0
        # Sum cost
        if other.cost is not None:
            self.cost = (self.cost or 0) + other.cost
        if other.total_runs > 0:
            self.total_runs += other.total_runs
            if other.average_duration is not None:
                if self.average_duration is None:
                    self.average_duration = other.average_duration
                else:
                    old_runs = self.total_runs - other.total_runs
                    total_duration = (self.average_duration * old_runs) + (other.average_duration * other.total_runs)
                    self.average_duration = total_duration / self.total_runs if self.total_runs > 0 else None


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
class Metrics:
    """Metrics for a run or message - token consumption, timing, and per-model breakdown.

    Used by RunOutput.metrics (run-level) and Message.metrics (message-level).
    At message level, fields like details, duration, cost, additional_metrics are None.
    """

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

    # Per-model metrics breakdown (only set at run level)
    # Keys: "model", "output_model", etc. (only includes model types that were used)
    # Values: List of ModelMetrics (for future fallback models support)
    details: Optional[Dict[str, List[ModelMetrics]]] = None

    # Provider-specific metrics (e.g., Anthropic's server_tool_use, service_tier)
    provider_metrics: Optional[Dict[str, Any]] = None

    # Cost of the run (currently only supported by some providers)
    cost: Optional[float] = None

    # Any additional metrics
    additional_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Remove the timer util if present
        metrics_dict.pop("timer", None)
        # Convert details ModelMetrics to dicts
        if metrics_dict.get("details") is not None:
            details_dict = {}
            valid_model_metrics_fields = {f.name for f in dc_fields(ModelMetrics)}
            for model_type, model_metrics_list in metrics_dict["details"].items():
                details_dict[model_type] = [
                    model_metric.to_dict()
                    if isinstance(model_metric, ModelMetrics)
                    else {k: v for k, v in model_metric.items() if k in valid_model_metrics_fields and v is not None}
                    for model_metric in model_metrics_list
                ]
            metrics_dict["details"] = details_dict
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }
        return metrics_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Metrics":
        """Create Metrics from a dict, filtering to valid fields and converting details."""
        valid = {f.name for f in dc_fields(cls)} - {"timer"}
        filtered = {k: v for k, v in data.items() if k in valid}
        # Convert details dicts to ModelMetrics objects
        if "details" in filtered and filtered["details"] is not None:
            converted_details = {}
            for model_type, model_metrics_list in filtered["details"].items():
                converted_details[model_type] = [
                    ModelMetrics.from_dict(model_metric) if isinstance(model_metric, dict) else model_metric
                    for model_metric in model_metrics_list
                ]
            filtered["details"] = converted_details
        return cls(**filtered)

    @classmethod
    def from_metrics(cls, other: "Metrics") -> "Metrics":
        """Backward compat: create a Metrics from another Metrics (copy token fields).

        Previously used to bridge MessageMetrics from RunMetrics. Now both are the same class,
        so this just copies token fields (excluding timer and details).
        """
        return cls(
            input_tokens=other.input_tokens,
            output_tokens=other.output_tokens,
            total_tokens=other.total_tokens,
            audio_input_tokens=other.audio_input_tokens,
            audio_output_tokens=other.audio_output_tokens,
            audio_total_tokens=other.audio_total_tokens,
            cache_read_tokens=other.cache_read_tokens,
            cache_write_tokens=other.cache_write_tokens,
            reasoning_tokens=other.reasoning_tokens,
            provider_metrics=other.provider_metrics,
        )

    def __add__(self, other: "Metrics") -> "Metrics":
        # Create new instance of the same type as self
        result_class = type(self)
        result = result_class(
            input_tokens=self.input_tokens + getattr(other, "input_tokens", 0),
            output_tokens=self.output_tokens + getattr(other, "output_tokens", 0),
            total_tokens=self.total_tokens + getattr(other, "total_tokens", 0),
            audio_total_tokens=self.audio_total_tokens + getattr(other, "audio_total_tokens", 0),
            audio_input_tokens=self.audio_input_tokens + getattr(other, "audio_input_tokens", 0),
            audio_output_tokens=self.audio_output_tokens + getattr(other, "audio_output_tokens", 0),
            cache_read_tokens=self.cache_read_tokens + getattr(other, "cache_read_tokens", 0),
            cache_write_tokens=self.cache_write_tokens + getattr(other, "cache_write_tokens", 0),
            reasoning_tokens=self.reasoning_tokens + getattr(other, "reasoning_tokens", 0),
        )
        # Preserve timer from self (important for streaming TTFT tracking)
        if self.timer is not None:
            result.timer = self.timer

        # Merge details dictionaries
        self_details = getattr(self, "details", None)
        other_details = getattr(other, "details", None)
        if self_details or other_details:
            result.details = {}
            if self_details:
                result.details.update(self_details)
            if other_details:
                # Merge lists for same model types
                for model_type, model_metrics_list in other_details.items():
                    if model_type in result.details:
                        result.details[model_type].extend(model_metrics_list)
                    else:
                        result.details[model_type] = model_metrics_list.copy()

        # Sum durations if both exist
        self_duration = getattr(self, "duration", None)
        other_duration = getattr(other, "duration", None)
        if self_duration is not None and other_duration is not None:
            result.duration = self_duration + other_duration
        elif self_duration is not None:
            result.duration = self_duration
        elif other_duration is not None:
            result.duration = other_duration

        # Sum time to first token if both exist
        self_time_to_first_token = getattr(self, "time_to_first_token", None)
        other_time_to_first_token = getattr(other, "time_to_first_token", None)
        if self_time_to_first_token is not None and other_time_to_first_token is not None:
            result.time_to_first_token = self_time_to_first_token + other_time_to_first_token
        elif self_time_to_first_token is not None:
            result.time_to_first_token = self_time_to_first_token
        elif other_time_to_first_token is not None:
            result.time_to_first_token = other_time_to_first_token

        # Merge provider_metrics dictionaries
        self_provider_metrics = getattr(self, "provider_metrics", None)
        other_provider_metrics = getattr(other, "provider_metrics", None)
        if self_provider_metrics is not None or other_provider_metrics is not None:
            result.provider_metrics = {}
            if self_provider_metrics:
                result.provider_metrics.update(self_provider_metrics)
            if other_provider_metrics:
                result.provider_metrics.update(other_provider_metrics)

        # Sum cost if either has it
        self_cost = getattr(self, "cost", None)
        other_cost = getattr(other, "cost", None)
        if self_cost is not None and other_cost is not None:
            result.cost = self_cost + other_cost
        elif self_cost is not None:
            result.cost = self_cost
        elif other_cost is not None:
            result.cost = other_cost

        # Merge additional_metrics dictionaries
        self_additional_metrics = getattr(self, "additional_metrics", None)
        other_additional_metrics = getattr(other, "additional_metrics", None)
        if self_additional_metrics is not None or other_additional_metrics is not None:
            result.additional_metrics = {}
            if self_additional_metrics:
                result.additional_metrics.update(self_additional_metrics)
            if other_additional_metrics:
                result.additional_metrics.update(other_additional_metrics)

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


@dataclass
class SessionMetrics:
    """Metrics for a session - aggregated token metrics from all runs.

    Flat dataclass (no inheritance). Does not include run-level timing
    fields like timer, time_to_first_token, or duration.
    """

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

    # Session-level aggregated stats
    # Average duration across all runs, in seconds
    average_duration: Optional[float] = None
    # Total number of runs in this session
    total_runs: int = 0

    # Per-model session breakdown (flat list, not dict)
    details: Optional[List[ModelMetrics]] = None

    # Carried from runs
    cost: Optional[float] = None
    provider_metrics: Optional[Dict[str, Any]] = None
    additional_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        # Convert details ModelMetrics to dicts
        if metrics_dict.get("details") is not None:
            valid_model_metrics_fields = {f.name for f in dc_fields(ModelMetrics)}
            details_list = [
                model_metric.to_dict()
                if isinstance(model_metric, ModelMetrics)
                else {k: v for k, v in model_metric.items() if k in valid_model_metrics_fields and v is not None}
                for model_metric in metrics_dict["details"]
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMetrics":
        """Create SessionMetrics from a dict, filtering to valid fields and converting details."""
        valid = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid}
        # Convert details to list of ModelMetrics objects
        if "details" in filtered and filtered["details"] is not None:
            details_raw = filtered["details"]
            if isinstance(details_raw, list):
                filtered["details"] = [
                    ModelMetrics.from_dict(model_metric) if isinstance(model_metric, dict) else model_metric
                    for model_metric in details_raw
                ]
            elif isinstance(details_raw, dict):
                # Old run-level format: Dict[str, List[ModelMetrics]] — flatten
                flat_details = []
                for model_type_details in details_raw.values():
                    if isinstance(model_type_details, list):
                        for detail in model_type_details:
                            if isinstance(detail, dict):
                                flat_details.append(ModelMetrics.from_dict(detail))
                            elif isinstance(detail, ModelMetrics):
                                flat_details.append(detail)
                filtered["details"] = flat_details if flat_details else None
            else:
                filtered.pop("details", None)
        return cls(**filtered)

    def __add__(self, other: "SessionMetrics") -> "SessionMetrics":
        """Sum two SessionMetrics objects."""
        other_total_runs = getattr(other, "total_runs", 0)
        total_runs = self.total_runs + other_total_runs

        # Calculate average duration
        average_duration = None
        other_average_duration = getattr(other, "average_duration", None)
        if self.average_duration is not None and other_average_duration is not None:
            # Weighted average
            total_duration = (self.average_duration * self.total_runs) + (other_average_duration * other_total_runs)
            average_duration = total_duration / total_runs if total_runs > 0 else None
        elif self.average_duration is not None:
            average_duration = self.average_duration
        elif other_average_duration is not None:
            average_duration = other_average_duration

        # Merge details lists by (provider, id) combination
        merged_details: Optional[List[ModelMetrics]] = None
        other_details = getattr(other, "details", None)
        if self.details or other_details:
            details_dict: Dict[Tuple[str, str], ModelMetrics] = {}

            for source_details in (self.details, other_details):
                if source_details:
                    for model_metrics in source_details:
                        key = (model_metrics.provider, model_metrics.id)
                        if key not in details_dict:
                            details_dict[key] = ModelMetrics.for_session(
                                model_metrics,
                                duration=model_metrics.average_duration,
                                total_runs=model_metrics.total_runs,
                            )
                        else:
                            details_dict[key].accumulate(model_metrics)

            merged_details = list(details_dict.values())

        # Sum cost
        cost = None
        other_cost = getattr(other, "cost", None)
        if self.cost is not None and other_cost is not None:
            cost = self.cost + other_cost
        elif self.cost is not None:
            cost = self.cost
        elif other_cost is not None:
            cost = other_cost

        # Merge provider_metrics
        merged_provider_metrics = None
        other_provider_metrics = getattr(other, "provider_metrics", None)
        if self.provider_metrics is not None or other_provider_metrics is not None:
            merged_provider_metrics = {}
            if self.provider_metrics:
                merged_provider_metrics.update(self.provider_metrics)
            if other_provider_metrics:
                merged_provider_metrics.update(other_provider_metrics)

        # Merge additional_metrics
        merged_additional_metrics = None
        other_additional_metrics = getattr(other, "additional_metrics", None)
        if self.additional_metrics is not None or other_additional_metrics is not None:
            merged_additional_metrics = {}
            if self.additional_metrics:
                merged_additional_metrics.update(self.additional_metrics)
            if other_additional_metrics:
                merged_additional_metrics.update(other_additional_metrics)

        result = SessionMetrics(
            input_tokens=self.input_tokens + getattr(other, "input_tokens", 0),
            output_tokens=self.output_tokens + getattr(other, "output_tokens", 0),
            total_tokens=self.total_tokens + getattr(other, "total_tokens", 0),
            audio_total_tokens=self.audio_total_tokens + getattr(other, "audio_total_tokens", 0),
            audio_input_tokens=self.audio_input_tokens + getattr(other, "audio_input_tokens", 0),
            audio_output_tokens=self.audio_output_tokens + getattr(other, "audio_output_tokens", 0),
            cache_read_tokens=self.cache_read_tokens + getattr(other, "cache_read_tokens", 0),
            cache_write_tokens=self.cache_write_tokens + getattr(other, "cache_write_tokens", 0),
            reasoning_tokens=self.reasoning_tokens + getattr(other, "reasoning_tokens", 0),
            cost=cost,
            average_duration=average_duration,
            total_runs=total_runs,
            details=merged_details,
            provider_metrics=merged_provider_metrics,
            additional_metrics=merged_additional_metrics,
        )

        return result


def accumulate_model_metrics(
    model_response: "ModelResponse",
    model: "Model",
    model_type: str,
    run_response: "Union[RunOutput, TeamRunOutput]",
) -> None:
    """Accumulate metrics from a model response into run_response.metrics.

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
        run_response.metrics = Metrics()
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
        audio_input_tokens=usage.audio_input_tokens or 0,
        audio_output_tokens=usage.audio_output_tokens or 0,
        audio_total_tokens=usage.audio_total_tokens or 0,
        cache_read_tokens=usage.cache_read_tokens or 0,
        cache_write_tokens=usage.cache_write_tokens or 0,
        reasoning_tokens=usage.reasoning_tokens or 0,
        time_to_first_token=usage.time_to_first_token,
        cost=usage.cost,
        provider_metrics=usage.provider_metrics,
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

    # Accumulate cost
    if usage.cost is not None:
        run_response.metrics.cost = (run_response.metrics.cost or 0) + usage.cost

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


# Backward compatibility aliases
RunMetrics = Metrics
MessageMetrics = Metrics
SessionModelMetrics = ModelMetrics
