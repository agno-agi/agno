"""
from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CometAPI(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],e with streaming example using CometAPI.
"""

from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=CometAPI(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Tool use with streaming
agent.print_response(
    "What's the current weather in Tokyo and what are some popular tourist attractions there?",
    stream=True,
)
