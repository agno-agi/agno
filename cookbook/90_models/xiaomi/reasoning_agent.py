"""
Xiaomi MiMo Reasoning Agent
===========================

Solve a logic puzzle with thinking mode on. Setting `use_thinking=True` makes the
model emit `reasoning_content`, which `show_full_reasoning=True` streams alongside
the answer so you can watch it work through the problem.
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
    model=MiMo(id="mimo-v2.5-pro", use_thinking=True),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(task, stream=True, show_full_reasoning=True)
