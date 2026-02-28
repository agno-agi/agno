from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional, Union


@dataclass
class ProviderRouting:
    """Configuration for OpenRouter provider routing.

    Controls how OpenRouter routes requests to different providers.
    See: https://openrouter.ai/docs/guides/routing/provider-selection

    Attributes:
        order: List of provider slugs to try in order (e.g. ["anthropic", "openai"]).
        allow_fallbacks: Whether to allow backup providers when the primary is unavailable.
        require_parameters: Only use providers that support all parameters in your request.
        data_collection: Control whether to use providers that may store data ("allow" or "deny").
        zdr: Restrict routing to only ZDR (Zero Data Retention) endpoints.
        enforce_distillable_text: Restrict routing to only models that allow text distillation.
        only: List of provider slugs to allow for this request.
        ignore: List of provider slugs to skip for this request.
        quantizations: List of quantization levels to filter by (e.g. ["int4", "int8"]).
        sort: Sort providers by price, throughput, or latency. Can be a string
            (e.g. "price") or a dict with "by" and "partition" fields.
        preferred_min_throughput: Preferred minimum throughput (tokens/sec). Can be a number
            or a dict with percentile cutoffs (p50, p75, p90, p99).
        preferred_max_latency: Preferred maximum latency (seconds). Can be a number
            or a dict with percentile cutoffs (p50, p75, p90, p99).
        max_price: The maximum pricing you want to pay for this request.
    """

    order: Optional[List[str]] = None
    allow_fallbacks: Optional[bool] = None
    require_parameters: Optional[bool] = None
    data_collection: Optional[str] = None
    zdr: Optional[bool] = None
    enforce_distillable_text: Optional[bool] = None
    only: Optional[List[str]] = None
    ignore: Optional[List[str]] = None
    quantizations: Optional[List[str]] = None
    sort: Optional[Union[str, Dict[str, Any]]] = None
    preferred_min_throughput: Optional[Union[int, float, Dict[str, Any]]] = None
    preferred_max_latency: Optional[Union[int, float, Dict[str, Any]]] = None
    max_price: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary, excluding None values."""
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None}
