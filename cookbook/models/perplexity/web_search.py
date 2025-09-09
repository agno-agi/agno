from agno.agent import Agent, RunOutput  # noqa
from agno.models.perplexity import Perplexity

agent = Agent(model=Perplexity(id="sonar-pro"), markdown=True)

# Print the response in the terminal
agent.print_response("Show me top 2 news stories from USA?")

# Get the response in a variable
# run: RunOutput = agent.run("What is happening in the world today?")
# print(run.content)
