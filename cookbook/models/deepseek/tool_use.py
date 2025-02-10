"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=DeepSeek(id="deepseek-chat"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

agent.print_response("Whats happening in France?")
