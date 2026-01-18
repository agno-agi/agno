from agno.agent import Agent
from agno.models.portkey import Portkey
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=Portkey(id="@first-integrati-707071/gpt-5-nano"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("What are the latest developments in AI gateways?", stream=True)
