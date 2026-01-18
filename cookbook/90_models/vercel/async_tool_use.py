"""Run `uv pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vercel import V0
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=V0(id="v0-1.0-md"),
    tools=[WebSearchTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
