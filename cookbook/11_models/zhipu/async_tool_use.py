"""
Async example using Zhipu with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.zhipu import Zhipu
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Zhipu(id="glm-4.7"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
