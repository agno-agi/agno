import asyncio
from typing import AsyncIterator  # noqa

from agno.agent import Agent, RunResponseEvent  # noqa
from agno.models.qwen import Qwen

agent = Agent(model=Qwen(id="qwen-plus", temperature=0.5), markdown=True)


async def main():
    # Get the response in a variable
    # async for chunk in agent.arun("Share a 2 sentence horror story", stream=True):
    #     print(chunk.content, end="", flush=True)

    # Print the response in the terminal
    await agent.aprint_response("Share a 2 sentence horror story", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
