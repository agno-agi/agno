"""
MiniMax Tool Use
================

Cookbook example for `minimax/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.minimax import MiniMax
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MiniMax(id="MiniMax-M2.5"),
    markdown=True,
    tools=[WebSearchTools()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("What is happening in France?", stream=True)
