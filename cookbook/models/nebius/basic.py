from agno.agent import Agent
from agno.models.nebius import Nebius

agent = Agent(
    model=Nebius(id="Qwen/Qwen3-235B-A22B"),
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

# Print the response in the terminal
agent.print_response("write a two sentence horror story")
