from typing import Iterator  # noqa
from agno.agent import Agent, RunResponse  # noqa
from agno.models.cloudflare import Cloudflare

agent = Agent(model=Cloudflare(id="@cf/meta/llama-3.1-8b-instruct"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
