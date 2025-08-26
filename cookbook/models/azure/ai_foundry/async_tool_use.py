"""
Async example using Claude with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.azure import AzureAIFoundry
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AzureAIFoundry(id="Cohere-command-r-08-2024"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?"))
