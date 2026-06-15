"""
This example demonstrates dynamic model routing with OrcaRouter.

Provide a `models` list and OrcaRouter will fall back through them in order when the
primary model encounters:
- Rate limits
- Timeouts
- Unavailability
- Model overload

This is sent to OrcaRouter as `extra_body={"models": [...], "route": "fallback"}`.

Tip: you can also set `id="orcarouter/auto"` to let OrcaRouter pick an upstream per
request based on your console routing policy (https://www.orcarouter.ai/console/routing).
"""

from agno.agent import Agent
from agno.models.orcarouter import OrcaRouter

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# If the primary model fails, OrcaRouter automatically tries the models defined in order.
agent = Agent(
    model=OrcaRouter(
        id="anthropic/claude-opus-4.8",  # Primary model
        models=[
            "deepseek/deepseek-v4-pro",  # First fallback model
            "openai/gpt-4o",  # Second fallback model
        ],
    ),
    markdown=True,
)

agent.print_response("Write a short poem about resilience and backup plans")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
