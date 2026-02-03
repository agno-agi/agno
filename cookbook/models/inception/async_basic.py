import asyncio

from agno.agent import Agent
from agno.models.inception import Inception

agent = Agent(model=Inception(id="mercury"), markdown=True)


async def main():
    run_response = await agent.arun("Share a 2 sentence horror story")
    print(run_response.content)


asyncio.run(main())
