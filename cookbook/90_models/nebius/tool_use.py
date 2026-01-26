from agno.agent import Agent
from agno.models.nebius import Nebius
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Nebius(id="Qwen/Qwen3-30B-A3B"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Whats happening in France?")
