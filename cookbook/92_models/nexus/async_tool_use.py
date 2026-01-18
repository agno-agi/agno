"""
Async example using Nexus with tool calls
"""

import asyncio

from agno.agent import Agent
from agno.models.nexus import Nexus
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Nexus(id="anthropic/claude-sonnet-4-20250514"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?"))
