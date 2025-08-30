from agno.agent import Agent
from agno.tools.wikipedia import WikipediaTools

agent = Agent(tools=[WikipediaTools()])
agent.print_response("Search wikipedia for 'ai'")
