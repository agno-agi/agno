"""
Async example using Claude with tool calls.
"""

import asyncio

from agno.agent.agent import Agent
from agno.models.cohere import Cohere
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Cohere(id="command-r-08-2024"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
