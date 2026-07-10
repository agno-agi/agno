"""
Moonshot Basic
==============

Cookbook example for `moonshot/basic.py`.
"""

from agno.agent import Agent
from agno.models.moonshot import MoonShot

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=MoonShot(id="kimi-k2-thinking"), markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story.")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story.", stream=True)
