"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=AIMLAPI(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?")
