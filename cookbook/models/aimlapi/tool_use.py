"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aimlapi import AIMLApi
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AIMLApi(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("Whats happening in France?")
