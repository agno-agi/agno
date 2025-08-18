from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.cohere import Cohere

agent = Agent(model=Cohere(id="command-a-03-2025"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
