"""Run `pip install duckduckgo-search` to install dependencies."""

import os

from agno.agent import Agent
from agno.models.qianfan import Qianfan
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Qianfan(id="deepseek-v3"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
