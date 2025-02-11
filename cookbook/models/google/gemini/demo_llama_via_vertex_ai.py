from agno.agent import Agent, RunResponse  # noqa
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(
        id="meta/llama-3.2-90b-vision-instruct-maas",
        vertexai=True,
        project_id="394942673418",
        location="us-central1",
    ),
    markdown=True,
)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Who made you?")
