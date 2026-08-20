"""
Basic Reasoning
=============================

Demonstrates basic reasoning with an explicit reasoning model.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
reasoning_agent = Agent(
    name="Reasoning Agent",
    model=OpenAIResponses(id="gpt-5.6"),
    reasoning_model=OpenAIResponses(id="o3-mini"),
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
