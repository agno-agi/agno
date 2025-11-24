from agno.agent import Agent, RunOutput  # noqa
from agno.models.lightning import Lightning

agent = Agent(model=Lightning(id="openai/gpt-5-nano"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
