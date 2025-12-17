"""
Async streaming example using CometAPI.
"""

import asyncio

from agno.agent import Agent
from agno.models.cometapi import CometAPI

agent = Agent(model=CometAPI(id="gpt-5-mini"), markdown=True)

# Async streaming response
asyncio.run(
    agent.aprint_response(
        "Write a short poem about artificial intelligence", stream=True
    )
)
