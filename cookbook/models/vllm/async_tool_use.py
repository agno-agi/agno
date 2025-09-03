"""Run `pip install ddgs` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vllm import vLLM
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=vLLM(id="Qwen/Qwen2.5-7B-Instruct", top_k=20, enable_thinking=False),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
