from agno.agent import Agent, RunOutput  # noqa
from agno.models.aimlapi import AIMLAPI

agent = Agent(model=AIMLAPI(id="gpt-4o-mini"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
