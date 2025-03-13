from agno.agent import Agent, RunResponse  # noqa
from agno.models.perplexity import Perplexity

agent = Agent(model=Perplexity(id="sonar-pro"), markdown=True)

# Get the response in a variable
# run: RunResponse = agent.run("What is happening in the world today?")
# print(run.content)

# Print the response in the terminal
agent.print_response("What is happening in the world today?")
