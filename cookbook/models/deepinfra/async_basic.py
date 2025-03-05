import asyncio

from agno.agent import Agent, RunResponse  # noqa
from agno.models.deepinfra import DeepInfra  # noqa

agent = Agent(
    model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
    markdown=True,
)

# Get the response in a variable
# def run_async() -> RunResponse:
#     return agent.arun("Share a 2 sentence horror story")
# response = asyncio.run(run_async())
# print(response.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
