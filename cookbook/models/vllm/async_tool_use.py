"""Run `pip install duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vllm import Vllm
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Vllm(id="Qwen/Qwen3-8B-FP8", top_k=20, enable_thinking=False),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
