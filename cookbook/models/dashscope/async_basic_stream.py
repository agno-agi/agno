import asyncio

from agno.agent import Agent  # noqa
from agno.models.dashscope import DashScope

agent = Agent(model=DashScope(id="qwen-plus", temperature=0.5), markdown=True)


async def main():
    # Get the response in a variable
    # async for chunk in agent.arun("Share a 2 sentence horror story", stream=True):
    #     print(chunk.content, end="", flush=True)

    # Print the response in the terminal
    await agent.aprint_response("Share a 2 sentence horror story", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
