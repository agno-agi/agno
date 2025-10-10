"""
This example demonstrates how to use dynamic model router with OpenRouter.

Dynamic models provide automatic failover when the primary model encounters:
- Rate limits
- Timeouts
- Unavailability
- Model overload

OpenRouter will automatically try the models defined in order until one succeeds.
"""

from agno.agent import Agent
from agno.models.openrouter import OpenRouter

# Create an agent with dynamic models
# If the primary model fails, OpenRouter will automatically try the models defined in order
agent = Agent(
    model=OpenRouter(
        id="anthropic/claude-sonnet-4",  # Primary model
        models=[
            "deepseek/deepseek-r1",  # First fallback model
            "openai/gpt-4o",  # Second fallback model
        ],
    ),
    markdown=True,
)

# Run the agent - it will use the primary model if available,
# or automatically fall back to alternative models if needed
agent.print_response("Write a short poem about resilience and backup plans")

# You can also check which model was actually used in the response
# by examining the response metadata (if available from OpenRouter)
