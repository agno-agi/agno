from typing import Iterator  # noqa
from phi.agent import Agent, RunResponse  # noqa
from phi.model.langdb import LangDB

agent = Agent(model=LangDB(id="llama3-1-70b-instruct-v1.0", project_id="langdb-project-id"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
