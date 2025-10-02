from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o", temperature=0.5), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
