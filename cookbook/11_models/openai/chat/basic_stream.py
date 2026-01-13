from typing import Iterator  # noqa
from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
