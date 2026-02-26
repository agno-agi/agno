"""
Extended Thinking - Complex Reasoning with Budget Control
==========================================================
Let Gemini "think" before responding for better answers on complex tasks.

Key concepts:
- thinking_budget: Token budget for thinking (0=disable, -1=dynamic, or a number)
- include_thoughts: If True, the model's reasoning is included in the response
- Best with Pro: Thinking is most effective with Gemini Pro models
- Trade-off: More thinking = better answers but higher latency and cost

Example prompts to try:
- "Solve the missionaries and cannibals river-crossing puzzle"
- "What is 127 * 389 + 256 * 741? Show your work."
- "Write a Python function to find all prime factors of a number. Think through edge cases."
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
        # Token budget for internal reasoning (higher = deeper thinking)
        thinking_budget=1280,
        # Show the model's chain of thought in the response
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Thinking budget guidelines:

- thinking_budget=0: Disable thinking (fastest, cheapest)
- thinking_budget=256: Light reasoning (simple math, basic logic)
- thinking_budget=1024: Moderate reasoning (multi-step problems)
- thinking_budget=2048: Deep reasoning (complex puzzles, proofs)
- thinking_budget=-1: Dynamic (model decides how much to think)

When to use thinking:
- Math and logic puzzles
- Code generation with edge cases
- Multi-step planning
- Analysis requiring chain-of-thought

When NOT to use thinking:
- Simple Q&A (adds unnecessary latency)
- Creative writing (thinking doesn't help much)
- Summarization (straightforward task)
"""
