"""Tool use example using OpenRouter with the Responses API.

This demonstrates using tools with OpenRouter's Responses API endpoint.
GPT reasoning items are replayed with tool calls between stateless requests.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenRouterResponses(id="openai/gpt-5.6-luna", reasoning_effort="high"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("What is the latest news about AI?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
