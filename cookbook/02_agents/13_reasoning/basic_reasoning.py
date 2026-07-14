"""
Basic Reasoning
=============================

Basic Reasoning.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
reasoning_agent = Agent(
    name="Reasoning Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    reasoning=True,
    reasoning_min_steps=2,
    reasoning_max_steps=6,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    reasoning_agent.print_response(
        "A bat and ball cost $1.10 total. The bat costs $1.00 more than the ball."
        " How much does the ball cost?",
        stream=True,
        show_full_reasoning=True,
    )
