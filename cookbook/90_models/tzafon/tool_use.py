"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.tzafon import Tzafon
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Tzafon(id="tzafon.northstar-cua-fast"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
