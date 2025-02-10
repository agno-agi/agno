from agno.agent import Agent
from agno.tools.shell import ShellTools

agent = Agent(tools=[ShellTools()], show_tool_calls=True)
agent.print_response("Show me the contents of the current directory", markdown=True)
