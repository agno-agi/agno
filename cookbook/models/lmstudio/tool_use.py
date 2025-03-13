"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.lmstudio import LMStudio
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=LMStudio(id="qwen2.5-7b-instruct-1m"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?")
