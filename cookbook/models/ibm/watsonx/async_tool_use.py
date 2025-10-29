"""
Async example using Claude with tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.ibm import WatsonX
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=WatsonX(id="mistralai/mistral-small-3-1-24b-instruct-2503"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
