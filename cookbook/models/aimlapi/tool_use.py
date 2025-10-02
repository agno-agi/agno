"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AIMLAPI(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?")
