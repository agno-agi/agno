"""
Async streaming tool use example using CometAPI.
"""

import asyncio

from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CometAPI(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Async streaming tool use
asyncio.run(
    agent.aprint_response(
        "Search for the latest developments in quantum computing and summarize them",
        stream=True,
    )
)
