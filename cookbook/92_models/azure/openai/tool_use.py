"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AzureOpenAI(id="gpt-5.2"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
