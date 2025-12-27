import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat

task = "9.11 and 9.9 -- which is bigger?"

regular_agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)
reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)

asyncio.run(regular_agent.aprint_response(task, stream=True))
asyncio.run(
    reasoning_agent.aprint_response(task, stream=True, show_full_reasoning=True)
)
