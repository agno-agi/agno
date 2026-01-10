"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=OpenRouter(id="openai/gpt-4o"),
    tools=[WebSearchTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
