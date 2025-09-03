"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vercel import v0
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=v0(id="v0-1.0-md"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
