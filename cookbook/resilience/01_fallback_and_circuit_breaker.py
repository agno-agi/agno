"""Resilience: Fallback Models and Circuit Breakers

This example demonstrates the Adaptive Agent Resilience Engine,
which provides declarative resilience for Agno agents.

Features shown:
- Automatic model fallback when the primary model fails
- Circuit breaker configuration for tool failure isolation
- Callback hooks for observability

Requirements:
    pip install agno openai
    export OPENAI_API_KEY="your-key"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.resilience import CircuitBreaker, ResiliencePolicy


def on_fallback(failed_model, fallback_model, error):
    """Callback invoked when a model fallback occurs."""
    print(f"Model {failed_model.__class__.__name__} failed: {error}")
    print(f"Switching to fallback: {fallback_model.__class__.__name__}")


# Create an agent with resilience policy
agent = Agent(
    name="Resilient Research Agent",
    description="A research agent with automatic model fallback",
    model=OpenAIChat(id="gpt-4o"),
    # Resilience: if gpt-4o fails (rate limit, outage), automatically try gpt-4o-mini
    resilience=ResiliencePolicy(
        fallback_models=[
            OpenAIChat(id="gpt-4o-mini"),
        ],
        circuit_breaker=CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
        ),
        on_fallback=on_fallback,
    ),
    # Built-in retry with exponential backoff (works alongside resilience)
    retries=2,
    exponential_backoff=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response("What is quantum computing? Explain in 3 sentences.")
