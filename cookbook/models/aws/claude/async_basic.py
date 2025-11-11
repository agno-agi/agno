import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.aws import Claude

agent = Agent(model=Claude(id="anthropic.claude-sonnet-4-20250514-v1:0"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
