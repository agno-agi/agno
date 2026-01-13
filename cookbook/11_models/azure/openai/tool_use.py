"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AzureOpenAI(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
