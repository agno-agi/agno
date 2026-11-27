"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.netmind import NetMind
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=NetMind(id="deepseek-ai/DeepSeek-V3-0324"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
