from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.pprint import apprint_run_response
import asyncio

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
)

async def streaming():
    async for response in agent.arun(message="Tell me a joke.", stream=True):
        print(response.content, end="", flush=True)
    
async def streaming_print():
    await agent.aprint_response(message="Tell me a joke.", stream=True)

async def streaming_pprint():
    await apprint_run_response(agent.arun(message="Tell me a joke.", stream=True))

if __name__ == "__main__":
    asyncio.run(streaming())
    # OR
    asyncio.run(streaming_print())
    # OR
    asyncio.run(streaming_pprint())