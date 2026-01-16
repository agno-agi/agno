"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.requesty import Requesty
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Requesty(id="openai/gpt-4o"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
