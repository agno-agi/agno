"""
Jinareader Tools
=============================

Demonstrates jinareader tools.
"""

from agno.agent import Agent
from agno.tools.jina import JinaReaderTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(tools=[JinaReaderTools()])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Summarize: https://github.com/agno-agi/agno")
