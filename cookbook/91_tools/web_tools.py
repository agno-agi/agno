"""
Web Tools
=============================

Demonstrates web tools.
"""

from agno.agent import Agent
from agno.tools.webtools import WebTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(tools=[WebTools()])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Tell me about https://tinyurl.com/57bmajz4")
