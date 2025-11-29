from typing import Dict, Optional, Union, Any

class PricingConfig:
    """Singleton registry for model pricing."""

    # Storage format: {"model_id": {"input": price_per_m, "output": price_per_m, "cache_read": price_per_m, "cache_write": price_per_m, "currency": str}}
    _prices: Dict[str, Dict[str, float]] = {}

    @classmethod
    def set_price(cls, model: Union[str, Any], input_price_per_million: float,
        output_price_per_million: float,
        cache_read_price_per_million: Optional[float] = None,
        cache_write_price_per_million: Optional[float] = None,
        currency: str = "USD",
):
        """
        Set pricing for a specific model (USD per 1 million tokens).
        
        Args:
            model: Model identifier (e.g., "gpt-5.1")
            input_token_price: Price per 1M input tokens
            output_token_price: Price per 1M output tokens
            cache_read_price_per_million: Price per 1M cached input tokens (optional)
            cache_write_price_per_million: Price per 1M cached write tokens (optional)
            currency: Currency code for display (default: "USD")

        """
        #Auto-extract ID if a Model object is passed
        model_id = model
        if hasattr(model, "id"):
            model_id = model.id
        elif not isinstance(model, str):
            # Fallback for unexpected objects that aren't strings and don't have .id
            model_id = str(model)
        cls._prices[model_id] = {
            "input": input_price_per_million / 1_000_000,
            "output": output_price_per_million / 1_000_000,
            "cache_read": (cache_read_price_per_million or 0.0) / 1_000_000,
            "cache_write": (cache_write_price_per_million or 0.0) / 1_000_000,
            "currency": currency,
        }

    @classmethod
    def get_price(cls, model: str) -> Optional[Dict[str, float]]:
        return cls._prices.get(model)

    @classmethod
    def calculate_cost(
        cls, 
        model: str, 
        input_tokens: int, 
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> Optional[Dict[str, float]]:
        """Returns None if pricing not set, otherwise returns dict with costs."""
        price = cls.get_price(model)
        if not price:
            return None
            
        input_cost = input_tokens * price["input"]
        output_cost = output_tokens * price["output"]
        cache_read_cost = cache_read_tokens * price["cache_read"]
        cache_write_cost = cache_write_tokens * price["cache_write"]
        
        total_cost = input_cost + output_cost + cache_read_cost + cache_write_cost
        
        return {
            "input_cost": input_cost,
            "output_cost": output_cost,
            "cache_read_cost": cache_read_cost,
            "cache_write_cost": cache_write_cost,
            "total_cost": total_cost,
            "currency": price["currency"]
        }