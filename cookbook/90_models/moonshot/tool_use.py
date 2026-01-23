from agno.agent import Agent
from agno.models.n1n import N1N
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=N1N(id="gkimi-k2-thinking"),
    markdown=True,
    tools=[WebSearchTools()],
)

agent.print_response("What is happening in France?", stream=True)
