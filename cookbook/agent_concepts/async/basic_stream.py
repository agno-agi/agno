import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You help people with their health and fitness goals.",
    instructions=["Recipes should be under 5 ingredients"],
    markdown=True,
)
# -*- Print a response to the cli
asyncio.run(agent.aprint_response("Share a breakfast recipe.", stream=True))
