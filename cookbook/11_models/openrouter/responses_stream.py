"""Streaming example using OpenRouter with the Responses API.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses

agent = Agent(
    model=OpenRouterResponses(id="anthropic/claude-sonnet-4"),
    markdown=True,
)

# Stream the response
agent.print_response("Write a short poem about the moon", stream=True)
