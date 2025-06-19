"""
This is a simple example of how to use the SerperApiTools class. You can obtain an API key from https://serper.dev/
"""

from agno.agent import Agent
from agno.tools.serperapi import SerperApiTools

agent = Agent(tools=[SerperApiTools(location="us")], show_tool_calls=True)
agent.print_response("Whats happening in the USA?", markdown=True)
