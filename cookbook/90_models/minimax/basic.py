"""
MiniMax Basic
=============

Cookbook example for `minimax/basic.py`.
"""

from agno.agent import Agent
from agno.models.minimax import MiniMax

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=MiniMax(id="MiniMax-M2.7"), markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story.")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story.", stream=True)
