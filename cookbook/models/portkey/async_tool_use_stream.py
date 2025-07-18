import asyncio

from agno.agent import Agent
from agno.models.portkey import Portkey
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Portkey(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

# Print the response in the terminal
asyncio.run(
    agent.aprint_response(
        "What are the latest developments in AI gateways?", stream=True
    )
)
