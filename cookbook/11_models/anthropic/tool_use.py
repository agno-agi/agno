"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?")
