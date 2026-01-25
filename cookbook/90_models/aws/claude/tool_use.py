"""Run `uv pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.aws import Claude
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Claude(id="global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
