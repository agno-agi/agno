from dataclasses import asdict, dataclass
from dataclasses import fields as dc_fields
from enum import Enum
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from agno.utils.timer import Timer


class ModelType(str, Enum):
    """Identifies the functional role of a model within an agent run."""

    MODEL = "model"
    OUTPUT_MODEL = "output_model"
    PARSER_MODEL = "parser_model"
    MEMORY_MODEL = "memory_model"
    REASONING_MODEL = "reasoning_model"
    SESSION_SUMMARY_MODEL = "session_summary_model"
    CULTURE_MODEL = "culture_model"
    LEARNING_MODEL = "learning_model"
    COMPRESSION_MODEL = "compression_model"


if TYPE_CHECKING:
    from agno.models.base import Model
    from agno.models.response import ModelResponse
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


# ---------------------------------------------------------------------------
# Base Metrics
# ---------------------------------------------------------------------------


@dataclass
class BaseMetrics:
    """Token consumption metrics shared across all metric types."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0
    audio_total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost: Optional[float] = None


# ---------------------------------------------------------------------------
# Model Metrics
# ---------------------------------------------------------------------------


@dataclass
class ModelMetrics(BaseMetrics):
    """Metrics for a specific model, aggregated by (provider, id).

    At run level: one entry per unique model in details[model_type].
    At session level: same structure, tokens summed across runs.
    """

    id: str = ""
    provider: str = ""
    provider_metrics: Optional[Dict[str, Any]] = None

    def accumulate(self, other: "ModelMetrics") -> None:
        """Add token counts and cost from another ModelMetrics into this one."""
        self.input_tokens += other.input_tokens or 0
        self.output_tokens += other.output_tokens or 0
        self.total_tokens += other.total_tokens or 0
        self.audio_input_tokens += other.audio_input_tokens or 0
        self.audio_output_tokens += other.audio_output_tokens or 0
        self.audio_total_tokens += other.audio_total_tokens or 0
        self.cache_read_tokens += other.cache_read_tokens or 0
        self.cache_write_tokens += other.cache_write_tokens or 0
        self.reasoning_tokens += other.reasoning_tokens or 0
        if other.cost is not None:
            self.cost = (self.cost or 0) + other.cost
        # Merge provider_metrics (sum numeric values, keep latest for others)
        if other.provider_metrics is not None:
            if self.provider_metrics is None:
                self.provider_metrics = {}
            for k, v in other.provider_metrics.items():
                if (
                    k in self.provider_metrics
                    and isinstance(v, (int, float))
                    and isinstance(self.provider_metrics[k], (int, float))
                ):
                    self.provider_metrics[k] += v
                else:
                    self.provider_metrics[k] = v

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        return {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, int) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelMetrics":
        valid = {f.name for f in dc_fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})


# ---------------------------------------------------------------------------
# Tool Call Metrics
# ---------------------------------------------------------------------------


@dataclass
class ToolCallMetrics:
    """Metrics for tool execution - only time-related fields."""

    timer: Optional[Timer] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        metrics_dict.pop("timer", None)
        return {k: v for k, v in metrics_dict.items() if v is not None and (not isinstance(v, int) or v != 0)}

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

        for field_name in ("start_time", "end_time"):
            if field_name in metrics_data and isinstance(metrics_data[field_name], str):
                try:
                    metrics_data[field_name] = datetime.fromisoformat(metrics_data[field_name]).timestamp()
                except (ValueError, AttributeError):
                    try:
                        metrics_data[field_name] = float(metrics_data[field_name])
                    except (ValueError, TypeError):
                        metrics_data[field_name] = None

        valid_fields = {f.name for f in dc_fields(cls)}
        metrics_data = {k: v for k, v in metrics_data.items() if k in valid_fields}
        return cls(**metrics_data)


# ---------------------------------------------------------------------------
# Message Metrics
# ---------------------------------------------------------------------------


@dataclass
class MessageMetrics(BaseMetrics):
    """Message-level metrics — token counts and timing. Used by Message.metrics."""

    timer: Optional[Timer] = None
    duration: Optional[float] = None
    time_to_first_token: Optional[float] = None
    # Transit field: set by providers, consumed by accumulate_model_metrics → ModelMetrics
    provider_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        metrics_dict.pop("timer", None)
        return {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, int) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageMetrics":
        valid = {f.name for f in dc_fields(cls)} - {"timer"}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def __add__(self, other: "MessageMetrics") -> "MessageMetrics":
        result = MessageMetrics(
            input_tokens=self.input_tokens + getattr(other, "input_tokens", 0),
            output_tokens=self.output_tokens + getattr(other, "output_tokens", 0),
            total_tokens=self.total_tokens + getattr(other, "total_tokens", 0),
            audio_input_tokens=self.audio_input_tokens + getattr(other, "audio_input_tokens", 0),
            audio_output_tokens=self.audio_output_tokens + getattr(other, "audio_output_tokens", 0),
            audio_total_tokens=self.audio_total_tokens + getattr(other, "audio_total_tokens", 0),
            cache_read_tokens=self.cache_read_tokens + getattr(other, "cache_read_tokens", 0),
            cache_write_tokens=self.cache_write_tokens + getattr(other, "cache_write_tokens", 0),
            reasoning_tokens=self.reasoning_tokens + getattr(other, "reasoning_tokens", 0),
        )
        # Sum cost
        self_cost = self.cost
        other_cost = getattr(other, "cost", None)
        if self_cost is not None and other_cost is not None:
            result.cost = self_cost + other_cost
        elif self_cost is not None:
            result.cost = self_cost
        elif other_cost is not None:
            result.cost = other_cost
        # Sum duration
        self_duration = self.duration
        other_duration = getattr(other, "duration", None)
        if self_duration is not None and other_duration is not None:
            result.duration = self_duration + other_duration
        elif self_duration is not None:
            result.duration = self_duration
        elif other_duration is not None:
            result.duration = other_duration
        # Preserve timer from self
        if self.timer is not None:
            result.timer = self.timer
        # Keep first non-None TTFT
        self_ttft = self.time_to_first_token
        other_ttft = getattr(other, "time_to_first_token", None)
        if self_ttft is not None:
            result.time_to_first_token = self_ttft
        elif other_ttft is not None:
            result.time_to_first_token = other_ttft
        # Merge provider_metrics (sum numeric values, keep latest for others)
        self_provider_metrics = self.provider_metrics
        other_provider_metrics = getattr(other, "provider_metrics", None)
        if self_provider_metrics is not None or other_provider_metrics is not None:
            merged_pm: Dict[str, Any] = {}
            if self_provider_metrics:
                merged_pm.update(self_provider_metrics)
            if other_provider_metrics:
                for k, v in other_provider_metrics.items():
                    if k in merged_pm and isinstance(v, (int, float)) and isinstance(merged_pm[k], (int, float)):
                        merged_pm[k] += v
                    else:
                        merged_pm[k] = v
            result.provider_metrics = merged_pm
        return result

    def __radd__(self, other: Any) -> "MessageMetrics":
        if other == 0:
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
        if self.timer is not None and self.time_to_first_token is None:
            self.time_to_first_token = self.timer.elapsed


# ---------------------------------------------------------------------------
# Run Metrics
# ---------------------------------------------------------------------------


@dataclass
class RunMetrics(BaseMetrics):
    """Run-level metrics with per-model breakdown.

    Used by RunOutput.metrics and TeamRunOutput.metrics.
    """

    timer: Optional[Timer] = None
    time_to_first_token: Optional[float] = None
    duration: Optional[float] = None

    # Per-model metrics breakdown
    # Keys: "model", "output_model", "memory_model", "eval_model", etc.
    # Values: List of ModelMetrics (one per unique provider+id)
    details: Optional[Dict[str, List[ModelMetrics]]] = None

    # Any additional metrics (e.g., eval_duration)
    additional_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        metrics_dict.pop("timer", None)
        # Convert details dicts properly
        if metrics_dict.get("details") is not None:
            details_dict = {}
            valid_model_metrics_fields = {f.name for f in dc_fields(ModelMetrics)}
            for model_type, model_metrics_list in metrics_dict["details"].items():
                details_dict[model_type] = [
                    {
                        k: v
                        for k, v in model_metric.items()
                        if k in valid_model_metrics_fields and v is not None and (not isinstance(v, int) or v != 0)
                    }
                    for model_metric in model_metrics_list
                ]
            metrics_dict["details"] = details_dict
        return {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, int) or v != 0) and (not isinstance(v, (dict, list)) or len(v) > 0)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunMetrics":
        """Create RunMetrics from a dict, filtering to valid fields and converting details."""
        valid = {f.name for f in dc_fields(cls)} - {"timer"}
        filtered = {k: v for k, v in data.items() if k in valid}
        # Convert details dicts to ModelMetrics objects
        if "details" in filtered and filtered["details"] is not None:
            converted_details: Dict[str, List[ModelMetrics]] = {}
            for model_type, model_metrics_list in filtered["details"].items():
                converted_details[model_type] = [
                    ModelMetrics.from_dict(model_metric) if isinstance(model_metric, dict) else model_metric
                    for model_metric in model_metrics_list
                ]
            filtered["details"] = converted_details
        return cls(**filtered)

    def __add__(self, other: "RunMetrics") -> "RunMetrics":
        result = RunMetrics(
            input_tokens=self.input_tokens + getattr(other, "input_tokens", 0),
            output_tokens=self.output_tokens + getattr(other, "output_tokens", 0),
            total_tokens=self.total_tokens + getattr(other, "total_tokens", 0),
            audio_input_tokens=self.audio_input_tokens + getattr(other, "audio_input_tokens", 0),
            audio_output_tokens=self.audio_output_tokens + getattr(other, "audio_output_tokens", 0),
            audio_total_tokens=self.audio_total_tokens + getattr(other, "audio_total_tokens", 0),
            cache_read_tokens=self.cache_read_tokens + getattr(other, "cache_read_tokens", 0),
            cache_write_tokens=self.cache_write_tokens + getattr(other, "cache_write_tokens", 0),
            reasoning_tokens=self.reasoning_tokens + getattr(other, "reasoning_tokens", 0),
        )
        # Preserve timer from self
        if self.timer is not None:
            result.timer = self.timer

        # Merge details — aggregate by (model_type, provider, id)
        self_details = self.details
        other_details = getattr(other, "details", None)
        if self_details or other_details:
            lookup: Dict[str, Dict[Tuple[str, str], ModelMetrics]] = {}

            for source_details in (self_details, other_details):
                if source_details:
                    for model_type, model_metrics_list in source_details.items():
                        if model_type not in lookup:
                            lookup[model_type] = {}
                        for mm in model_metrics_list:
                            key = (mm.provider, mm.id)
                            if key in lookup[model_type]:
                                lookup[model_type][key].accumulate(mm)
                            else:
                                lookup[model_type][key] = ModelMetrics.from_dict(mm.to_dict())

            result.details = {model_type: list(entries.values()) for model_type, entries in lookup.items()}

        # Sum durations
        self_duration = self.duration
        other_duration = getattr(other, "duration", None)
        if self_duration is not None and other_duration is not None:
            result.duration = self_duration + other_duration
        elif self_duration is not None:
            result.duration = self_duration
        elif other_duration is not None:
            result.duration = other_duration

        # Keep earliest TTFT
        self_ttft = self.time_to_first_token
        other_ttft = getattr(other, "time_to_first_token", None)
        if self_ttft is not None and other_ttft is not None:
            result.time_to_first_token = min(self_ttft, other_ttft)
        elif self_ttft is not None:
            result.time_to_first_token = self_ttft
        elif other_ttft is not None:
            result.time_to_first_token = other_ttft

        # Sum cost
        self_cost = self.cost
        other_cost = getattr(other, "cost", None)
        if self_cost is not None and other_cost is not None:
            result.cost = self_cost + other_cost
        elif self_cost is not None:
            result.cost = self_cost
        elif other_cost is not None:
            result.cost = other_cost

        # Merge additional_metrics (sum numeric values, keep latest for others)
        self_am = self.additional_metrics
        other_am = getattr(other, "additional_metrics", None)
        if self_am is not None or other_am is not None:
            result.additional_metrics = {}
            if self_am:
                result.additional_metrics.update(self_am)
            if other_am:
                for k, v in other_am.items():
                    if (
                        k in result.additional_metrics
                        and isinstance(v, (int, float))
                        and isinstance(result.additional_metrics[k], (int, float))
                    ):
                        result.additional_metrics[k] += v
                    else:
                        result.additional_metrics[k] = v

        return result

    def __radd__(self, other: Any) -> "RunMetrics":
        if other == 0:
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
        if self.timer is not None and self.time_to_first_token is None:
            self.time_to_first_token = self.timer.elapsed


# Backward-compat alias
Metrics = RunMetrics


# ---------------------------------------------------------------------------
# Session metrics – aggregated across runs
# ---------------------------------------------------------------------------


@dataclass
class SessionMetrics(BaseMetrics):
    """Session-level aggregated metrics across runs.

    details has the same type as RunMetrics.details: Dict[str, List[ModelMetrics]].
    Tokens in each ModelMetrics entry are summed across all runs.
    """

    # Same type as RunMetrics.details — Dict keyed by model type
    details: Optional[Dict[str, List[ModelMetrics]]] = None

    # Carried from runs
    additional_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        if metrics_dict.get("details") is not None:
            valid_model_metrics_fields = {f.name for f in dc_fields(ModelMetrics)}
            details_dict = {}
            for model_type, model_metrics_list in metrics_dict["details"].items():
                details_dict[model_type] = [
                    {
                        k: v
                        for k, v in model_metric.items()
                        if k in valid_model_metrics_fields and v is not None and (not isinstance(v, int) or v != 0)
                    }
                    for model_metric in model_metrics_list
                ]
            metrics_dict["details"] = details_dict
        return {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, int) or v != 0) and (not isinstance(v, (dict, list)) or len(v) > 0)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMetrics":
        """Create SessionMetrics from a dict, converting details dicts to ModelMetrics objects."""
        valid = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid}

        if "details" in filtered and filtered["details"] is not None:
            details_raw = filtered["details"]
            if isinstance(details_raw, dict):
                converted: Dict[str, List[ModelMetrics]] = {}
                for model_type, model_metrics_list in details_raw.items():
                    if isinstance(model_metrics_list, list):
                        converted[model_type] = [
                            ModelMetrics.from_dict(model_metric) if isinstance(model_metric, dict) else model_metric
                            for model_metric in model_metrics_list
                        ]
                filtered["details"] = converted if converted else None
            else:
                filtered.pop("details", None)

        return cls(**filtered)

    def accumulate_from_run(self, run_metrics: "RunMetrics") -> None:
        """Accumulate run-level RunMetrics into this SessionMetrics."""
        # Accumulate token metrics
        self.input_tokens += run_metrics.input_tokens
        self.output_tokens += run_metrics.output_tokens
        self.total_tokens += run_metrics.total_tokens
        self.audio_input_tokens += run_metrics.audio_input_tokens
        self.audio_output_tokens += run_metrics.audio_output_tokens
        self.audio_total_tokens += run_metrics.audio_total_tokens
        self.cache_read_tokens += run_metrics.cache_read_tokens
        self.cache_write_tokens += run_metrics.cache_write_tokens
        self.reasoning_tokens += run_metrics.reasoning_tokens

        # Accumulate cost
        if run_metrics.cost is not None:
            self.cost = (self.cost or 0) + run_metrics.cost

        # Merge additional_metrics (sum numeric values, keep latest for others)
        if run_metrics.additional_metrics is not None:
            if self.additional_metrics is None:
                self.additional_metrics = {}
            for k, v in run_metrics.additional_metrics.items():
                if (
                    k in self.additional_metrics
                    and isinstance(v, (int, float))
                    and isinstance(self.additional_metrics[k], (int, float))
                ):
                    self.additional_metrics[k] += v
                else:
                    self.additional_metrics[k] = v

        # Merge per-model details: Dict[str, List[ModelMetrics]] -> Dict[str, List[ModelMetrics]]
        if run_metrics.details:
            if self.details is None:
                self.details = {}

            for model_type, model_metrics_list in run_metrics.details.items():
                if model_type not in self.details:
                    self.details[model_type] = []
                existing_list = self.details[model_type]

                for model_metrics in model_metrics_list:
                    # Find existing entry by (provider, id)
                    found = False
                    for existing in existing_list:
                        if existing.provider == model_metrics.provider and existing.id == model_metrics.id:
                            existing.accumulate(model_metrics)
                            found = True
                            break
                    if not found:
                        # Create a copy so we don't alias the run-level entry
                        existing_list.append(ModelMetrics.from_dict(model_metrics.to_dict()))

    def __add__(self, other: "SessionMetrics") -> "SessionMetrics":
        """Sum two SessionMetrics objects."""

        # Merge details dicts — aggregate by (model_type, provider, id)
        merged_details: Optional[Dict[str, List[ModelMetrics]]] = None
        other_details = getattr(other, "details", None)
        if self.details or other_details:
            # Build lookup: model_type -> (provider, id) -> ModelMetrics
            lookup: Dict[str, Dict[Tuple[str, str], ModelMetrics]] = {}

            for source_details in (self.details, other_details):
                if source_details:
                    for model_type, model_metrics_list in source_details.items():
                        if model_type not in lookup:
                            lookup[model_type] = {}
                        for mm in model_metrics_list:
                            key = (mm.provider, mm.id)
                            if key in lookup[model_type]:
                                lookup[model_type][key].accumulate(mm)
                            else:
                                lookup[model_type][key] = ModelMetrics.from_dict(mm.to_dict())

            merged_details = {mt: list(entries.values()) for mt, entries in lookup.items()}

        # Sum cost
        cost = None
        other_cost = getattr(other, "cost", None)
        if self.cost is not None and other_cost is not None:
            cost = self.cost + other_cost
        elif self.cost is not None:
            cost = self.cost
        elif other_cost is not None:
            cost = other_cost

        # Merge additional_metrics (sum numeric values, keep latest for others)
        merged_am = None
        other_am = getattr(other, "additional_metrics", None)
        if self.additional_metrics is not None or other_am is not None:
            merged_am = {}
            if self.additional_metrics:
                merged_am.update(self.additional_metrics)
            if other_am:
                for k, v in other_am.items():
                    if k in merged_am and isinstance(v, (int, float)) and isinstance(merged_am[k], (int, float)):
                        merged_am[k] += v
                    else:
                        merged_am[k] = v

        return SessionMetrics(
            input_tokens=self.input_tokens + getattr(other, "input_tokens", 0),
            output_tokens=self.output_tokens + getattr(other, "output_tokens", 0),
            total_tokens=self.total_tokens + getattr(other, "total_tokens", 0),
            audio_input_tokens=self.audio_input_tokens + getattr(other, "audio_input_tokens", 0),
            audio_output_tokens=self.audio_output_tokens + getattr(other, "audio_output_tokens", 0),
            audio_total_tokens=self.audio_total_tokens + getattr(other, "audio_total_tokens", 0),
            cache_read_tokens=self.cache_read_tokens + getattr(other, "cache_read_tokens", 0),
            cache_write_tokens=self.cache_write_tokens + getattr(other, "cache_write_tokens", 0),
            reasoning_tokens=self.reasoning_tokens + getattr(other, "reasoning_tokens", 0),
            cost=cost,
            details=merged_details,
            additional_metrics=merged_am,
        )

    def __radd__(self, other: Any) -> "SessionMetrics":
        if other == 0:
            return self
        return self + other


# ---------------------------------------------------------------------------
# Accumulation helpers
# ---------------------------------------------------------------------------


def accumulate_model_metrics(
    model_response: "ModelResponse",
    model: "Model",
    model_type: "Union[ModelType, str]",
    run_response: "Union[RunOutput, TeamRunOutput]",
) -> None:
    """Accumulate metrics from a model response into run_response.metrics.

    Finds or creates a ModelMetrics entry in details[model_type] by (provider, id).
    Sums tokens into the existing entry if found, otherwise creates a new one.
    Also accumulates top-level token counts and cost.
    """
    if model_response.response_usage is None:
        return

    usage = model_response.response_usage

    # Initialize run_response.metrics if None
    if run_response.metrics is None:
        run_response.metrics = RunMetrics()
        run_response.metrics.start_timer()

    metrics = run_response.metrics

    if metrics.details is None:
        metrics.details = {}

    # Coerce token values
    input_tokens = usage.input_tokens or 0
    output_tokens = usage.output_tokens or 0
    total_tokens = usage.total_tokens or 0
    audio_input_tokens = usage.audio_input_tokens or 0
    audio_output_tokens = usage.audio_output_tokens or 0
    audio_total_tokens = usage.audio_total_tokens or 0
    cache_read_tokens = usage.cache_read_tokens or 0
    cache_write_tokens = usage.cache_write_tokens or 0
    reasoning_tokens = usage.reasoning_tokens or 0

    model_id = model.id
    model_provider = model.get_provider()

    # Create ModelMetrics entry
    model_metrics = ModelMetrics(
        id=model_id,
        provider=model_provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        audio_input_tokens=audio_input_tokens,
        audio_output_tokens=audio_output_tokens,
        audio_total_tokens=audio_total_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        cost=usage.cost,
        provider_metrics=usage.provider_metrics,
    )

    # Find-and-add by (provider, id), or append new entry
    _model_type_key = model_type.value if isinstance(model_type, ModelType) else model_type
    entries = metrics.details.get(_model_type_key)
    if entries is None:
        metrics.details[_model_type_key] = [model_metrics]
    else:
        for entry in entries:
            if entry.id == model_id and entry.provider == model_provider:
                entry.accumulate(model_metrics)
                break
        else:
            entries.append(model_metrics)

    # Accumulate top-level token counts
    metrics.input_tokens += input_tokens
    metrics.output_tokens += output_tokens
    metrics.total_tokens += total_tokens
    metrics.audio_input_tokens += audio_input_tokens
    metrics.audio_output_tokens += audio_output_tokens
    metrics.audio_total_tokens += audio_total_tokens
    metrics.cache_read_tokens += cache_read_tokens
    metrics.cache_write_tokens += cache_write_tokens
    metrics.reasoning_tokens += reasoning_tokens

    # Accumulate cost
    if usage.cost is not None:
        metrics.cost = (metrics.cost or 0) + usage.cost


def accumulate_eval_metrics(
    eval_response: "RunOutput",
    run_response: "Union[RunOutput, TeamRunOutput]",
    prefix: str = "eval",
) -> None:
    """Accumulate child agent metrics from a RunOutput into the original run_response.

    Merges a child agent's metrics under "{prefix}_model" keys in details.
    """
    if eval_response.metrics is None:
        return

    eval_metrics = eval_response.metrics

    if run_response.metrics is None:
        run_response.metrics = RunMetrics()
        run_response.metrics.start_timer()

    if run_response.metrics.details is None:
        run_response.metrics.details = {}

    # Copy over model details under "{prefix}_<model_type>" keys
    if eval_metrics.details:
        for model_type, model_metrics_list in eval_metrics.details.items():
            prefixed_key = f"{prefix}_{model_type}" if not model_type.startswith(f"{prefix}_") else model_type
            if prefixed_key not in run_response.metrics.details:
                run_response.metrics.details[prefixed_key] = []

            # Find-and-add by (provider, id) into the prefixed list
            for mm in model_metrics_list:
                found = False
                for existing in run_response.metrics.details[prefixed_key]:
                    if existing.provider == mm.provider and existing.id == mm.id:
                        existing.accumulate(mm)
                        found = True
                        break
                if not found:
                    run_response.metrics.details[prefixed_key].append(ModelMetrics.from_dict(mm.to_dict()))

    # Accumulate top-level token counts
    run_response.metrics.input_tokens += eval_metrics.input_tokens
    run_response.metrics.output_tokens += eval_metrics.output_tokens
    run_response.metrics.total_tokens += eval_metrics.total_tokens
    run_response.metrics.audio_input_tokens += eval_metrics.audio_input_tokens
    run_response.metrics.audio_output_tokens += eval_metrics.audio_output_tokens
    run_response.metrics.audio_total_tokens += eval_metrics.audio_total_tokens
    run_response.metrics.cache_read_tokens += eval_metrics.cache_read_tokens
    run_response.metrics.cache_write_tokens += eval_metrics.cache_write_tokens
    run_response.metrics.reasoning_tokens += eval_metrics.reasoning_tokens

    # Accumulate cost
    if eval_metrics.cost is not None:
        run_response.metrics.cost = (
            run_response.metrics.cost if run_response.metrics.cost is not None else 0
        ) + eval_metrics.cost

    # Track eval duration separately
    if prefix == "eval" and eval_metrics.duration is not None:
        if run_response.metrics.additional_metrics is None:
            run_response.metrics.additional_metrics = {}
        existing = run_response.metrics.additional_metrics.get("eval_duration", 0)
        run_response.metrics.additional_metrics["eval_duration"] = existing + eval_metrics.duration


def merge_background_metrics(
    run_response: "Union[RunOutput, TeamRunOutput]",
    background_metrics: "List[RunMetrics]",
) -> None:
    """Merge background task metrics into run_response.metrics on the main thread.

    Each background task (memory, culture, learning) accumulates metrics into its
    own isolated RunMetrics collector. After all tasks complete, this function
    merges those collectors into the real run_response — avoiding concurrent
    mutation of shared state.
    """
    for bg_metrics in background_metrics:
        if bg_metrics is None:
            continue

        if run_response.metrics is None:
            run_response.metrics = RunMetrics()

        metrics = run_response.metrics

        # Accumulate top-level token counts
        metrics.input_tokens += bg_metrics.input_tokens
        metrics.output_tokens += bg_metrics.output_tokens
        metrics.total_tokens += bg_metrics.total_tokens
        metrics.audio_input_tokens += bg_metrics.audio_input_tokens
        metrics.audio_output_tokens += bg_metrics.audio_output_tokens
        metrics.audio_total_tokens += bg_metrics.audio_total_tokens
        metrics.cache_read_tokens += bg_metrics.cache_read_tokens
        metrics.cache_write_tokens += bg_metrics.cache_write_tokens
        metrics.reasoning_tokens += bg_metrics.reasoning_tokens

        # Accumulate cost
        if bg_metrics.cost is not None:
            metrics.cost = (metrics.cost or 0) + bg_metrics.cost

        # Merge per-model details
        if bg_metrics.details:
            if metrics.details is None:
                metrics.details = {}
            for model_type, model_metrics_list in bg_metrics.details.items():
                if model_type not in metrics.details:
                    metrics.details[model_type] = []
                for mm in model_metrics_list:
                    found = False
                    for existing in metrics.details[model_type]:
                        if existing.provider == mm.provider and existing.id == mm.id:
                            existing.accumulate(mm)
                            found = True
                            break
                    if not found:
                        metrics.details[model_type].append(ModelMetrics.from_dict(mm.to_dict()))

        # Merge additional_metrics (sum numeric values, keep latest for others)
        if bg_metrics.additional_metrics:
            if metrics.additional_metrics is None:
                metrics.additional_metrics = {}
            for k, v in bg_metrics.additional_metrics.items():
                if (
                    k in metrics.additional_metrics
                    and isinstance(v, (int, float))
                    and isinstance(metrics.additional_metrics[k], (int, float))
                ):
                    metrics.additional_metrics[k] += v
                else:
                    metrics.additional_metrics[k] = v
