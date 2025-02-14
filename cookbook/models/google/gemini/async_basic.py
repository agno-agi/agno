import asyncio

from agno.agent import Agent, RunResponse  # noqa
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp",
        instructions=["You are a basic agent that writes short stories."],
    ),
    markdown=True,
)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
