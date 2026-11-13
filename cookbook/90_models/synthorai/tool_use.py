"""
Synthorai Tool Use
==================

Cookbook example for `synthorai/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.synthorai import Synthorai
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Synthorai(id="claude-opus-5"),
    markdown=True,
    tools=[WebSearchTools()],
)

agent.print_response("What is happening in France?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
