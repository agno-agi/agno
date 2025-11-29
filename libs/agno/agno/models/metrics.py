from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from agno.utils.timer import Timer
from agno.utils.pricing import PricingConfig

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

    # -- Cost Estimates --
    input_cost: Optional[float] = None
    output_cost: Optional[float] = None
    cache_read_cost: Optional[float] = None
    cache_write_cost: Optional[float] = None
    total_cost: Optional[float] = None
    currency: Optional[str] = None

    # Time metrics
    timer: Optional[Timer] = None
    time_to_first_token: Optional[float] = None
    duration: Optional[float] = None

    # Provider-specific metrics
    provider_metrics: Optional[dict] = None

    # Any additional metrics
    additional_metrics: Optional[dict] = None

    def calculate_cost(self, model_id: str):
        """Populate cost metrics based on the PricingConfig registry."""
        costs = PricingConfig.calculate_cost(
            model=model_id, 
            input_tokens=self.input_tokens, 
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens
        )
        if costs:
            self.input_cost = costs["input_cost"]
            self.output_cost = costs["output_cost"]
            self.cache_read_cost = costs["cache_read_cost"]
            self.cache_write_cost = costs["cache_write_cost"]
            self.total_cost = costs["total_cost"]
            self.currency = costs["currency"]

    def to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        metrics_dict.pop("timer", None)
        
        cleaned_dict = {}
        for k, v in metrics_dict.items():
            # Skip None, Zero values (except 0 if it's not a boolean check), or empty dicts
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0):
                #Format costs to avoid scientific notation (e.g. 2.6e-05 -> "0.000026")
                if "cost" in k and isinstance(v, float):
                    cleaned_dict[k] = f"{v:.10f}".rstrip("0").rstrip(".")
                else:
                    cleaned_dict[k] = v
        if self.total_cost is not None and self.currency:
            cleaned_dict["currency"] = self.currency                
        return cleaned_dict

    def _sum_optional_floats(self, val1: Optional[float], val2: Optional[float]) -> Optional[float]:
        """Helper to sum costs safely."""
        if val1 is None and val2 is None:
            return None
        return (val1 or 0.0) + (val2 or 0.0)

    def __add__(self, other: "Metrics") -> "Metrics":
        result_class = type(self)
        
        # Calculate sums for costs
        new_input_cost = self._sum_optional_floats(self.input_cost, other.input_cost)
        new_output_cost = self._sum_optional_floats(self.output_cost, other.output_cost)
        new_cache_read_cost = self._sum_optional_floats(self.cache_read_cost, other.cache_read_cost)
        new_cache_write_cost = self._sum_optional_floats(self.cache_write_cost, other.cache_write_cost)
        new_total_cost = self._sum_optional_floats(self.total_cost, other.total_cost)
        new_currency = self.currency or other.currency
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
            # Pass calculated costs
            input_cost=new_input_cost,
            output_cost=new_output_cost,
            cache_read_cost=new_cache_read_cost,
            cache_write_cost=new_cache_write_cost,
            total_cost=new_total_cost,
            currency=new_currency,
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