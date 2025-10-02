import asyncio

from agno.agent import Agent
from agno.models.cerebras import Cerebras
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?"))
