from agno.agent import Agent
from agno.tools.linkup import LinkupTools

agent = Agent(tools=[LinkupTools()], show_tool_calls=True)
agent.print_response("Whats happening in France?", markdown=True)
