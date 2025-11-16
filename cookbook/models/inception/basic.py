from agno.agent import Agent, RunOutput  # noqa
from agno.models.inception import Inception

agent = Agent(model=Inception(id="mercury"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("What is a diffusion model?")
# print(run.content)

# Print the response in the terminal
agent.print_response("What is a diffusion model?")
