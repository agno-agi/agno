"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.cohere import Cohere
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Cohere(id="command-a-03-2025"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
