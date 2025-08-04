from agno.agent import Agent
from agno.tools.tavily import TavilyTools

agent = Agent(tools=[TavilyTools()])
agent.print_response("Search tavily for 'language models'", markdown=True)
