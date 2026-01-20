from typing import Iterator  # noqa
from agno.agent import Agent, RunOutput  # noqa
from agno.models.langdb import LangDB

agent = Agent(
    model=LangDB(id="llama3-1-70b-instruct-v1.0"),
    markdown=True,
)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
