from os import getenv

from agno.agent import Agent, RunResponse  # noqa
from agno.models.xai import xAI

agent = Agent(model=xAI(id="grok-beta"), api_key=getenv("XAI_API_KEY"), markdown=True)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
