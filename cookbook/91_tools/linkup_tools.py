"""
Linkup Tools
=============================

Demonstrates linkup tools.
"""

from agno.agent import Agent
from agno.tools.linkup import LinkupTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(tools=[LinkupTools()])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What's the latest news in French politics?", markdown=True)
