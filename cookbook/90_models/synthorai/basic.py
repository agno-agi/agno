"""
Synthorai Basic
===============

Cookbook example for `synthorai/basic.py`.
"""

from agno.agent import Agent
from agno.models.synthorai import Synthorai

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Synthorai(id="claude-opus-5"), markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story.")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story.", stream=True)
