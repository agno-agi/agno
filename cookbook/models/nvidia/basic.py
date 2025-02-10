from agno.agent import Agent, RunResponse  # noqa
from agno.models.nvidia import Nvidia

agent = Agent(model=Nvidia(id="meta/llama-3.3-70b-instruct"), markdown=True)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
