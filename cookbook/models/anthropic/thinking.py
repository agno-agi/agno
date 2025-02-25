from agno.agent import Agent, RunResponse  # noqa
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-3-7-sonnet-20250219",
        max_tokens=8192,
        thinking={"type": "enabled", "budget_tokens": 4096},
    ),
    markdown=True,
)

# Get the response in a variable
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
