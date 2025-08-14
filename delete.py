import asyncio

from agno.agent.agent import Agent

agent = Agent()


async def arun():
    async for event in agent.arun("Hello, how are you?"):
        print(event)


async def arun_streaming():
    async for event in agent.arun("Hello, how are you?"):
        print(event)


def run():
    res = agent.run("Hello, how are you?")
    print(res)


def run_streaming():
    for event in agent.run("Hello, how are you?", stream=True):
        print(event)


if __name__ == "__main__":
    asyncio.run(arun_streaming())
