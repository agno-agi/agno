from agno.agent.agent import Agent
from agno.models.cerebras.cerebras import Cerebras
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Cerebras(
        id="gpt-oss-120b",
    ),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Whats happening in France?")
