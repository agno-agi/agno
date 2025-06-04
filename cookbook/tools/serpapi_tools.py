from agno.agent import Agent
from agno.tools.serpapi import SerpApiTools

agent = Agent(tools=[SerpApiTools()], show_tool_calls=True)
agent.print_response("Whats happening in the USA?", markdown=True)
