"""Use the official asynchronous SDK through Agent.arun."""

import asyncio

from typesafe_sdk import Noul

from agno.agent import Agent
from agno.models.typesafe import Jev
from agno.utils.pprint import pprint_run_response

agent = Agent(
    model=Jev(
        questions={
            "urgent": Noul(instructions="Does state.input describe an urgent issue?")
        }
    )
)


async def main():
    response = await agent.arun("Our production workspace is down")
    pprint_run_response(response)
    response = await agent.arun("The submit button is wrong color")
    pprint_run_response(response)


if __name__ == "__main__":
    asyncio.run(main())
