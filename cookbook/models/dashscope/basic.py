from agno.agent import Agent, RunOutput  # noqa
from agno.models.dashscope import DashScope

agent = Agent(model=DashScope(id="qwen-plus", temperature=0.5), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
