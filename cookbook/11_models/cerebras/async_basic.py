import asyncio

from agno.agent import Agent
from agno.models.cerebras import Cerebras

agent = Agent(
    model=Cerebras(id="llama-3.3-70b"),
    markdown=True,
)

asyncio.run(agent.aprint_response("write a two sentence horror story"))
