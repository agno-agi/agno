from agno.agent import Agent
from agno.tools.linkup import LinkupTools

agent = Agent(tools=[LinkupTools()], show_tool_calls=True)
agent.print_response("Search linkup for 'language models'", markdown=True)
