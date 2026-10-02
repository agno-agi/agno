"""Use the official asynchronous SDK through Agent.aprint_response."""

import asyncio

from typesafe_sdk import Noul

from agno.agent import Agent
from agno.models.typesafe import Jev

agent = Agent(
    model=Jev(
        questions={
            "urgent": Noul(instructions="Does state.input describe an urgent issue?")
        }
    )
)


async def main():
    await agent.aprint_response("Our production workspace is down")
    await agent.aprint_response("The submit button is wrong color")


if __name__ == "__main__":
    asyncio.run(main())
