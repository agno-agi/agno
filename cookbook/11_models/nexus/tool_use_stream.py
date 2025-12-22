"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.nexus import Nexus
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Nexus(id="anthropic/claude-sonnet-4-20250514"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
