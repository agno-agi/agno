from agno.agent import Agent, RunOutput  # noqa
from agno.models.vercel import V0

agent = Agent(model=V0(id="v0-1.0-md"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")

# agent.print_response("Create a simple web app that displays a random number between 1 and 100.")
