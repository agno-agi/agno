from agno.agent import Agent, RunOutput  # noqa
from agno.models.deepinfra import DeepInfra  # noqa


agent = Agent(
    model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story")
