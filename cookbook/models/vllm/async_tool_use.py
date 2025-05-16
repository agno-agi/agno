"""Run `pip install duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vllm import Vllm
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Vllm(id="microsoft/Phi-3-mini-4k-instruct"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("What's happening in France?", stream=True))
