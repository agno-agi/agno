import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.pprint import apprint_run_response

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
)


async def basic():
    response = await agent.arun(input="Tell me a joke.")
    print(response.content)


async def basic_print():
    await agent.aprint_response(input="Tell me a joke.")


async def basic_pprint():
    response = await agent.arun(input="Tell me a joke.")
    await apprint_run_response(response)


if __name__ == "__main__":
    asyncio.run(basic())
    # OR
    asyncio.run(basic_print())
    # OR
    asyncio.run(basic_pprint())
