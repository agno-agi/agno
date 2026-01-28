"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.lightning import Lightning
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Lightning(id="openai/gpt-5-nano"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
