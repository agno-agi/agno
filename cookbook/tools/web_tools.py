from agno.agent import Agent
from agno.tools.webtools import WebTools

agent = Agent(tools=[WebTools()])
agent.print_response("Tell me about https://tinyurl.com/57bmajz4")
