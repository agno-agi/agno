from agno.agent import Agent
from agno.models.n1n import N1N

agent = Agent(
    model=N1N(id="gpt-4o"),
    show_tool_calls=True,
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Whats the weather in NV?", stream=True)
