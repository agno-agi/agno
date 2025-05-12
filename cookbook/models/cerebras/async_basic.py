import asyncio

from agno.agent import Agent
from agno.models.cerebras import Cerebras

agent = Agent(
    model=Cerebras(id="llama-4-scout-17b-16e-instruct"),
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

asyncio.run(agent.aprint_response("write a two sentence horror story"))
