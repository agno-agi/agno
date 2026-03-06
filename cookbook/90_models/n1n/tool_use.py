"""
N1N Tool Use
============

Cookbook example for `n1n/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.n1n import N1N
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=N1N(id="gpt-5-mini"),
    markdown=True,
    tools=[WebSearchTools()],
)

agent.print_response("What is happening in France?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
