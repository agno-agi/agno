"""
Runcrate Tool Use
=================

Cookbook example for `runcrate/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.runcrate import Runcrate
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Runcrate(),
    markdown=True,
    tools=[WebSearchTools()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("What is happening in France?", stream=True)
