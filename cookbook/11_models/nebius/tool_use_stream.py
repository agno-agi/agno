from agno.agent import Agent
from agno.models.nebius import Nebius
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Nebius(id="Qwen/Qwen3-30B-A3B"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Whats happening in France?", stream=True)
