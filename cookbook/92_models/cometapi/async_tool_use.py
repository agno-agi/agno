"""
Async tool use example using CometAPI.
"""

import asyncio

from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CometAPI(id="gpt-5"),
    tools=[DuckDuckGoTools(enable_search=True, enable_news=True)],
    markdown=True,
)

# Async tool use
asyncio.run(agent.aprint_response("What's the latest news about AI?"))
