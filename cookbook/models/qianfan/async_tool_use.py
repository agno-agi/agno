"""
Async example using Mistral with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.qianfan import Qianfan
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Qianfan(id="deepseek-v3"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
