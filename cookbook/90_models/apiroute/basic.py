"""
API Route Basic
===============

Cookbook example for `apiroute/basic.py`.
"""

from agno.agent import Agent
from agno.models.apiroute import ApiRoute

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=ApiRoute(id="claude-3-7-sonnet-20250219"), markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story.")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story.", stream=True)
