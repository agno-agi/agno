"""Tool use example using OpenRouter with the Responses API.

This demonstrates using tools with OpenRouter's Responses API endpoint.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenRouterResponses(id="openai/gpt-oss-20b", enable_reasoning=True),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("What is the latest news about AI?", stream=True)
