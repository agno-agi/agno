"""
Newspaper Tools
=============================

Demonstrates newspaper tools.
"""

from agno.agent import Agent
from agno.tools.newspaper import NewspaperTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(tools=[NewspaperTools()])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Please summarize https://en.wikipedia.org/wiki/Language_model"
    )
