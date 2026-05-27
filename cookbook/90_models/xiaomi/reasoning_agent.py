"""
Xiaomi MiMo Reasoning Agent
===========================

Cookbook example for `xiaomi/reasoning_agent.py`.
"""

from agno.agent import Agent
from agno.models.xiaomi import MiMo

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

task = (
    "Three missionaries and three cannibals need to cross a river. "
    "They have a boat that can carry up to two people at a time. "
    "If, at any time, the cannibals outnumber the missionaries on either side of the river, the cannibals will eat the missionaries. "
    "How can all six people get across the river safely? Provide a step-by-step solution and show the solution as an ascii diagram."
)

agent = Agent(
    model=MiMo(id="mimo-v2.5-pro", thinking={"type": "enabled"}),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(task, stream=True, show_full_reasoning=True)
