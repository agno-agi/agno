from agno.agent import Agent
from agno.tools.serperapi import SerperApiTools

agent = Agent(tools=[SerperApiTools(api_key="",gl="us")], show_tool_calls=True)
agent.print_response("Whats happening in the USA?", markdown=True)
