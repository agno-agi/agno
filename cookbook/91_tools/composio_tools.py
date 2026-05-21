"""
Composio Tools
=============================

Demonstrates composio tools.
"""

from agno.agent import Agent
from composio_agno import Action, ComposioToolSet

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


toolset = ComposioToolSet()
composio_tools = toolset.get_tools(
    actions=[Action.GITHUB_STAR_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER]
)
agent = Agent(tools=composio_tools)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Can you star agno-agi/agno repo?")
