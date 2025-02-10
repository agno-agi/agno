"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenRouter(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
