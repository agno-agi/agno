from agno.agent import Agent, RunOutput  # noqa
from agno.models.azure import AzureOpenAIResponses

agent = Agent(model=AzureOpenAIResponses(id="gpt-4o-mini"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response on the terminal
agent.print_response("Share a 2 sentence horror story")
