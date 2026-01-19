from agno.agent import Agent
from agno.models.cerebras import Cerebras
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Cerebras(id="llama-3.3-70b"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Whats happening in France?")
