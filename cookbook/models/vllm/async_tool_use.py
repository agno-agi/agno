"""Run `pip install duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.vllm import vLLMOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=vLLMOpenAI(
        id="microsoft/Phi-3-mini-4k-instruct", top_k=20, enable_thinking=False
    ),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
