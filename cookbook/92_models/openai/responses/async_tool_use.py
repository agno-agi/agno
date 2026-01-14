"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
