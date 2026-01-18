"""Basic example using OpenRouter with the Responses API.

OpenRouter's Responses API (beta) provides OpenAI-compatible access to multiple
AI models through a unified interface.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses

agent = Agent(
    model=OpenRouterResponses(id="anthropic/claude-sonnet-4"),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
