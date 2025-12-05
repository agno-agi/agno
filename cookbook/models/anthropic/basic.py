from agno.agent import Agent, RunOutput  # noqa
from agno.models.anthropic import Claude

agent = Agent(model=Claude(id="claude-sonnet-4-5-20250929"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
