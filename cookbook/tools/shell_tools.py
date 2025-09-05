from agno.agent import Agent
from agno.tools.shell import ShellTools

agent = Agent(tools=[ShellTools()])
agent.print_response("Show me the contents of the current directory", markdown=True)
