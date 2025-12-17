"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vercel import V0
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=V0(id="v0-1.0-md"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
