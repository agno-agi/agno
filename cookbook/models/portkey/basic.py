from agno.agent import Agent, RunOutput  # noqa
from agno.models.portkey import Portkey

# Create model using Portkey
model = Portkey(
    id="@first-integrati-707071/gpt-5-nano",
)

agent = Agent(model=model, markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("What is Portkey and why would I use it as an AI gateway?")
# print(run.content)

# Print the response in the terminal
agent.print_response("What is Portkey and why would I use it as an AI gateway?")
