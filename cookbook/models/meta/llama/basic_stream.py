from typing import Iterator  # noqa
from agno.agent import Agent, RunResponse  # noqa
from agno.models.meta import Llama

agent = Agent(model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
