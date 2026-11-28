"""
Sarvam Reasoning Agent
======================

Solve a logic puzzle with a higher reasoning effort. Sarvam returns the thinking
trace in `reasoning_content`, and `show_full_reasoning=True` streams it alongside
the answer so you can watch the model work through the problem.

`sarvam-105b` defaults to `reasoning_effort="low"`; set it to `"medium"` or
`"high"` for harder tasks, or `"none"` to turn reasoning off.
"""

from agno.agent import Agent
from agno.models.sarvam import Sarvam

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
    model=Sarvam(id="sarvam-105b", reasoning_effort="high"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(task, stream=True, show_full_reasoning=True)
