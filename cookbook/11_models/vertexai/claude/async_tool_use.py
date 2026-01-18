"""
Async example using Claude with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.vertexai.claude import Claude
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Claude(id="claude-sonnet-4@20250514"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
