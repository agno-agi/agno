"""Run `pip install duckduckgo-search` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.models.perplexity import Perplexity
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Perplexity(id="sonar-pro"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
asyncio.run(
    agent.aprint_response(
        "Whats happening in France? Use the DuckDuckGo tool to find the latest news.",
        stream=True,
    )
)
