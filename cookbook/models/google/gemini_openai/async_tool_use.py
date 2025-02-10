"""
Async example using GeminiOpenAI with tool calls.
"""

import asyncio

from agno.agent.agent import Agent
from agno.models.google import GeminiOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=GeminiOpenAI(id="gemini-2.0-flash-exp"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
