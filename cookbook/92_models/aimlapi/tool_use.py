"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AIMLAPI(id="gpt-5.2"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?")
