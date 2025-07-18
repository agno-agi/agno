from agno.agent import Agent, RunResponseEvent  # noqa
from agno.models.deepseek import DeepSeek

agent = Agent(model=DeepSeek(id="deepseek-chat"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunResponseEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
