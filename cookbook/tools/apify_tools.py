from agno.agent import Agent
from agno.tools.apify import ApifyTools

agent = Agent(tools=[ApifyTools()], show_tool_calls=True)
agent.print_response("Tell me about https://docs.agno.com/introduction", markdown=True)
