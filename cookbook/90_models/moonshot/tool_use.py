"""
Moonshot Tool Use
=================

Cookbook example for `moonshot/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.moonshot import MoonShot
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=MoonShot(id="kimi-k2-thinking"),
    markdown=True,
    tools=[WebSearchTools()],
)

agent.print_response("What is happening in France?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
