"""
Async example using Mistral with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.mistral.mistral import MistralChat
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=MistralChat(id="mistral-large-latest"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
