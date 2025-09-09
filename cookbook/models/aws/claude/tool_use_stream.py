"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aws import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(id="anthropic.claude-3-5-sonnet-20240620-v1:0"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
