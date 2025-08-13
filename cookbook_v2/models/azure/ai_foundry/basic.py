from agno.agent import Agent, RunResponse  # noqa
from agno.models.azure import AzureAIFoundry

agent = Agent(model=AzureAIFoundry(id="Phi-4"), markdown=True)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response on the terminal
agent.print_response("Share a 2 sentence horror story")
