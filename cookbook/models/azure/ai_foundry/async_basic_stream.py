import asyncio

from agno.agent import Agent
from agno.models.azure import AzureAIFoundry

assistant = Agent(
    model=AzureAIFoundry(id="Phi-4"),
    description="You help people with their health and fitness goals.",
    instructions=["Recipes should be under 5 ingredients"],
)
# -*- Print a response to the cli
asyncio.run(
    assistant.aprint_response("Share a breakfast recipe.", markdown=True, stream=True)
)
