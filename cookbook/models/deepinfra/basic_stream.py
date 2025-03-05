from typing import Iterator  # noqa

from agno.agent import Agent, RunResponse  # noqa
from agno.models.deepinfra import DeepInfra  # noqa

agent = Agent(
    model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
    markdown=True,
)

# Get the response in a variable
run_response: Iterator[RunResponse] = agent.run(
    "Share a 2 sentence horror story", stream=True
)
for chunk in run_response:
    print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
