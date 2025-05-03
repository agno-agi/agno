"""Run `pip install duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.cloudflare import Cloudflare
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Cloudflare(id="@cf/meta/llama-3.1-8b-instruct"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
