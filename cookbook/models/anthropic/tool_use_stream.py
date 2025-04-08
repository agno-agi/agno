"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20240620"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    add_history_to_messages=True,
    markdown=True,
)
agent.cli_app("Whats happening in France?", stream=True)
