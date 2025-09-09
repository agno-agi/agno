import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.ibm import WatsonX

agent = Agent(
    model=WatsonX(id="mistralai/mistral-small-3-1-24b-instruct-2503"), markdown=True
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
