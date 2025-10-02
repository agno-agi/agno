from typing import Iterator  # noqa

from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.azure import AzureOpenAI

agent = Agent(model=AzureOpenAI(id="gpt-4o-mini"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response on the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
