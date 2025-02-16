import asyncio

from agno.models.openai import OpenAIRealtime
from agno.agent import Agent

agent = Agent(model=OpenAIRealtime(id="gpt-4o-realtime-preview"))

asyncio.run(agent.acli_app(stream=True))

# asyncio.run(agent.live())