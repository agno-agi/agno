import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.sambanova import Sambanova

agent = Agent(model=Sambanova(id="Meta-Llama-3.1-8B-Instruct"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
