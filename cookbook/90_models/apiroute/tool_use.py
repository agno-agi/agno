"""
API Route Tool Use
==================

Cookbook example for `apiroute/tool_use.py`.
"""

from agno.agent import Agent
from agno.models.apiroute import ApiRoute
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=ApiRoute(id="claude-3-7-sonnet-20250219"),
    markdown=True,
    tools=[WebSearchTools()],
)

agent.print_response("What is the latest news about generative AI?", stream=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
