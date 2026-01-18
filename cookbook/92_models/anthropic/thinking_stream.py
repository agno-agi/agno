from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(
        id="claude-3-7-sonnet-20250219",
        max_tokens=2048,
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Share a very scary 2 sentence horror story", stream=True)
