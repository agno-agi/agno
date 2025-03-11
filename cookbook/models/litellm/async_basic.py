from agno.agent import Agent
from agno.models.litellm import LiteLLM
import asyncio

openai_agent = Agent(
    model=LiteLLM(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
)

asyncio.run(openai_agent.aprint_response("Share a 2 sentence horror story"))
