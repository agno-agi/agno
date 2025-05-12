from typing import Iterator

from agno.agent import Agent, RunResponse
from agno.models.ai_ml_api import AIMlAPI

agent = Agent(model=AIMlAPI(id="gpt-4o-mini"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunResponse] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
