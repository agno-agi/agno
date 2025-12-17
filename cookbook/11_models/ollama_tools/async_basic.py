import asyncio

from agno.agent import Agent
from agno.models.ollama import OllamaTools

agent = Agent(
    model=OllamaTools(id="llama3.1:8b"),
    description="You help people with their health and fitness goals.",
    instructions=["Recipes should be under 5 ingredients"],
)
# -*- Print a response to the cli
asyncio.run(agent.aprint_response("Share a breakfast recipe.", markdown=True))
