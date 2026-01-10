"""
Async example using Claude with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Claude(id="claude-haiku-4-5-20251001"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
