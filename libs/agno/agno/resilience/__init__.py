"""Adaptive Agent Resilience Engine.

Composable, declarative resilience primitives for Agno agents:
- ResiliencePolicy: top-level configuration object
- FallbackModel helpers: automatic model switching on provider errors
- CircuitBreaker: per-tool failure isolation with open/half-open/closed states
"""

from agno.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerState
from agno.resilience.fallback import atry_with_fallback, try_with_fallback
from agno.resilience.policy import ResiliencePolicy

__all__ = [
    "ResiliencePolicy",
    "CircuitBreaker",
    "CircuitBreakerState",
    "try_with_fallback",
    "atry_with_fallback",
]
