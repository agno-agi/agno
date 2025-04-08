"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

def sample_tool(input: str) -> str:
    """Sample tool function."""
    return input

def sample_tool1(input: str) -> str:
    """Sample tool function."""
    return input

def sample_tool2(input: str) -> str:
    """Sample tool function."""
    return input

agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20240620"),
    tools=[sample_tool, sample_tool1, sample_tool2],
    show_tool_calls=True,
    add_history_to_messages=True,
    markdown=True,
)
agent.cli_app("Whats happening in France?", stream=True)
