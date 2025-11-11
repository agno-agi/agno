"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aws import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(id="anthropic.claude-sonnet-4-20250514-v1:0"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
