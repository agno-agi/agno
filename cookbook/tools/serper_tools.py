"""
This is a simple example of how to use the SerperTools class. You can obtain an API key from https://serper.dev/
"""

from agno.agent import Agent
from agno.tools.serper import SerperTools

agent = Agent(tools=[SerperTools(location="us")], show_tool_calls=True)
agent.print_response("Whats happening in the USA?", markdown=True)
