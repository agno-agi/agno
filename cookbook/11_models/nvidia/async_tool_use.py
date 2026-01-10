"""
Async example using Nvidia with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.nvidia import Nvidia
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
