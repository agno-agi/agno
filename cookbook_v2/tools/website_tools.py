from agno.agent import Agent
from agno.tools.website import WebsiteTools

agent = Agent(tools=[WebsiteTools()])
agent.print_response(
    "Search web page: 'https://docs.agno.com/introduction'", markdown=True
)
