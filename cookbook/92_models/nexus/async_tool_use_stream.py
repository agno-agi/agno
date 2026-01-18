"""
Async example using Nexus with tool call streaming.
"""

import asyncio

from agno.agent import Agent
from agno.models.nexus import Nexus
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Nexus(id="anthropic/claude-sonnet-4-20250514"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
