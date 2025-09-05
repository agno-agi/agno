from typing import Iterator  # noqa
from agno.agent import Agent, RunOutput  # noqa
from agno.models.vercel import V0

agent = Agent(model=V0(id="v0-1.0-md"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
