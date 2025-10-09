"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.requesty import Requesty
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Requesty(id="openai/gpt-4o"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
