"""Model fallback example using OpenRouter with the Responses API.

This demonstrates using fallback models with OpenRouter's dynamic model routing.
If the primary model fails due to rate limits, timeouts, or unavailability,
OpenRouter will automatically try the fallback models in order.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenRouterResponses(
        id="openai/gpt-oss-20b",
        # Fallback models if primary fails
        models=[
            "openai/gpt-oss-20b",
            "openai/gpt-4o",
        ],
    ),
    markdown=True,
)

agent.print_response("Write a haiku about coding", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
