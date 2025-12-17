"""
Async example using AIMlAPI with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.aimlapi import AIMLAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AIMLAPI(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
