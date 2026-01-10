"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-001"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
