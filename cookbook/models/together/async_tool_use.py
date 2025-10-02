"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.together import Together
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Together(id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
