import asyncio

from agno.agent import Agent
from agno.models.aws import AwsBedrock

agent = Agent(model=AwsBedrock(id="mistral.mistral-small-2402-v1:0"), markdown=True)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
