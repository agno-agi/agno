"""
Shell Tools
=============================

Demonstrates shell tools.
"""

from agno.agent import Agent
from agno.tools.shell import ShellTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(tools=[ShellTools()])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Show me the contents of the current directory", markdown=True)
