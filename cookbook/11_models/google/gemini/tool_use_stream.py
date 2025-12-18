"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-001"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
