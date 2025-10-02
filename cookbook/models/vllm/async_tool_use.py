"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vllm import VLLM
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=VLLM(id="Qwen/Qwen2.5-7B-Instruct", top_k=20, enable_thinking=False),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
