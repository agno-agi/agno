"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.fireworks import Fireworks
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Fireworks(id="accounts/fireworks/models/llama-v3p1-405b-instruct"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
