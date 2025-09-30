from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.nvidia import Nvidia

agent = Agent(model=Nvidia(id="meta/llama-3.3-70b-instruct"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
