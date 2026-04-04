import asyncio

from agno.agent import Agent
from agno.models.inception import Inception

agent = Agent(model=Inception(id="mercury"), markdown=True)


async def main():
    async for chunk in agent.arun("Share a 2 sentence horror story", stream=True):
        print(chunk.content, end="", flush=True)
    print()


asyncio.run(main())
