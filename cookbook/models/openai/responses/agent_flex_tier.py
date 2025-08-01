import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(model=OpenAIResponses(id="o4-mini", service_tier="flex"), markdown=True, debug_mode=True)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
