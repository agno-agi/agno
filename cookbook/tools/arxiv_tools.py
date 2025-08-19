from agno.agent import Agent
from agno.tools.arxiv import ArxivTools

agent = Agent(tools=[ArxivTools()])
agent.print_response("Search arxiv for 'language models'", markdown=True)
