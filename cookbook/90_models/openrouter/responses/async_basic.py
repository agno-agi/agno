"""Async example using OpenRouter with the Responses API.

This demonstrates async usage with OpenRouter's Responses API endpoint.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

import asyncio

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses

agent = Agent(
    model=OpenRouterResponses(id="anthropic/claude-sonnet-4"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
