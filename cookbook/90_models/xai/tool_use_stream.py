"""Build a Web Search Agent using xAI."""

from agno.agent import Agent
from agno.models.xai import xAI
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=xAI(id="grok-2"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
