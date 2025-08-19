"""
Basic async example using Claude.
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
