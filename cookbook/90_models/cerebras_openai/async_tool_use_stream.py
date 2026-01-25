import asyncio

from agno.agent import Agent
from agno.models.cerebras import CerebrasOpenAI
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=CerebrasOpenAI(id="llama-3.3-70b"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
