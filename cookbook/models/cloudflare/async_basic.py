import asyncio

from agno.agent import Agent, RunResponse  # noqa
from agno.models.cloudflare import Cloudflare

agent = Agent(model=Cloudflare(id="@cf/meta/llama-3.1-8b-instruct"), markdown=True)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
