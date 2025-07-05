"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.qwen import Qwen
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Qwen(id="qwen-max"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("What are the latest developments in artificial intelligence? Please search for recent news.") 