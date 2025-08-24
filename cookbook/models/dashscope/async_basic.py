import asyncio

from agno.agent import Agent, RunResponse  # noqa
from agno.models.qwen import Qwen

agent = Agent(model=Qwen(id="qwen-plus", temperature=0.5), markdown=True)

# Get the response in a variable
# run: RunResponse = await agent.arun("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
