"""
7. Extended Thinking
====================
Enable Gemini's extended thinking for complex reasoning tasks.
The model "thinks" before responding, producing better answers for
logic puzzles, math, and multi-step problems.

Parameters:
    thinking_budget: Token budget for thinking (0=disable, -1=dynamic, or a number)
    include_thoughts: Include the model's reasoning in the response

Run:
    python cookbook/gemini_3/7_thinking.py

Example prompt:
    Classic missionaries and cannibals river-crossing puzzle
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
thinking_agent = Agent(
    name="Thinking Agent",
    model=Gemini(
        id="gemini-3.1-pro-preview",
        thinking_budget=1280,
        include_thoughts=True,
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    task = (
        "Three missionaries and three cannibals need to cross a river. "
        "They have a boat that can carry up to two people at a time. "
        "If, at any time, the cannibals outnumber the missionaries on either "
        "side of the river, the cannibals will eat the missionaries. "
        "How can all six people get across the river safely? "
        "Provide a step-by-step solution and show the solution as an ascii diagram."
    )

    thinking_agent.print_response(task, stream=True)
