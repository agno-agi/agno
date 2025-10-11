"""
Async example using Lightning with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.lightning import Lightning
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Lightning(id="openai/gpt-5-nano"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
