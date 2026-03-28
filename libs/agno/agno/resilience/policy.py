"""Resilience policy configuration for Agno agents.

Provides a single declarative configuration object that composes
fallback models, circuit breakers, and lifecycle callbacks.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from pydantic import BaseModel

from agno.resilience.circuit_breaker import CircuitBreaker


class ResiliencePolicy(BaseModel):
    """Declarative resilience configuration for an Agent.

    Compose fallback models, circuit breakers, and callbacks into
    a single policy object that the agent applies during execution.

    Attributes:
        fallback_models: Ordered list of fallback models to try when the primary
            model raises a ModelProviderError or ModelRateLimitError.
        circuit_breaker: Circuit breaker configuration for tool-level failure isolation.
        on_fallback: Optional callback invoked when a fallback is triggered.
            Signature: (failed_model, fallback_model, error) -> None
        on_circuit_open: Optional callback invoked when a circuit breaker opens.
            Signature: (tool_name) -> None

    Example:
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.resilience import ResiliencePolicy, CircuitBreaker

        agent = Agent(
            name="Resilient Agent",
            model=OpenAIChat(id="gpt-4o"),
            resilience=ResiliencePolicy(
                fallback_models=[OpenAIChat(id="gpt-4o-mini")],
                circuit_breaker=CircuitBreaker(
                    failure_threshold=5,
                    recovery_timeout=60.0,
                ),
            ),
        )
        ```
    """

    fallback_models: Optional[List[Any]] = None
    circuit_breaker: Optional[CircuitBreaker] = None
    on_fallback: Optional[Callable] = None
    on_circuit_open: Optional[Callable] = None

    model_config = {"arbitrary_types_allowed": True}
