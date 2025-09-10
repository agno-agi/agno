"""
Async example using Mistral with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.mistral.mistral import MistralChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=MistralChat(id="mistral-large-latest"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
