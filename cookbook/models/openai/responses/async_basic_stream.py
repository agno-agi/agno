import asyncio
from typing import Iterator  # noqa

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIResponses

agent = Agent(model=OpenAIResponses(id="gpt-4o"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
