from typing import Any, Dict

from pydantic import BaseModel


class AggregatedMetrics(BaseModel):
    """Aggregated metrics for a given day or month"""

    id: str
    day: int
    month: int

    created_at: int
    updated_at: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    audio_tokens: int
    input_audio_tokens: int
    output_audio_tokens: int
    cached_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    prompt_tokens: int
    completion_tokens: int
    prompt_tokens_details: Dict[str, Any]
    completion_tokens_details: Dict[str, Any]
    additional_metrics: Dict[str, Any]
    time_to_first_token: float
    time: float

    @classmethod
    def from_dict(cls, metrics_dict: Dict[str, Any]) -> "AggregatedMetrics":
        return cls(
            id=metrics_dict["id"],
            day=metrics_dict["day"],
            month=metrics_dict["month"],
            created_at=metrics_dict["created_at"],
            updated_at=metrics_dict["updated_at"],
            input_tokens=metrics_dict["input_tokens"],
            output_tokens=metrics_dict["output_tokens"],
            total_tokens=metrics_dict["total_tokens"],
            audio_tokens=metrics_dict["audio_tokens"],
            input_audio_tokens=metrics_dict["input_audio_tokens"],
            output_audio_tokens=metrics_dict["output_audio_tokens"],
            cached_tokens=metrics_dict["cached_tokens"],
            cache_write_tokens=metrics_dict["cache_write_tokens"],
            reasoning_tokens=metrics_dict["reasoning_tokens"],
            prompt_tokens=metrics_dict["prompt_tokens"],
            completion_tokens=metrics_dict["completion_tokens"],
            prompt_tokens_details=metrics_dict["prompt_tokens_details"],
            completion_tokens_details=metrics_dict["completion_tokens_details"],
            additional_metrics=metrics_dict["additional_metrics"],
            time_to_first_token=metrics_dict["time_to_first_token"],
            time=metrics_dict["time"],
        )
