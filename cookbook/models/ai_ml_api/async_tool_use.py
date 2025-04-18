"""Run `pip install duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.ai_ml_api import AIMlAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AIMlAPI(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
