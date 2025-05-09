"""Run `pip install agno llama-api-client duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.meta import Llama
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
)
asyncio.run(agent.aprint_response("What's happening in France?", stream=True))
