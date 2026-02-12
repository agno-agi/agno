"""
Reasoning With Model
=============================

Use a separate reasoning model with configurable step limits.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    # Use a separate model for the reasoning/thinking step
    reasoning_model=OpenAIResponses(id="gpt-5-mini"),
    reasoning=True,
    reasoning_min_steps=2,
    reasoning_max_steps=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "A farmer has 17 sheep. All but 9 die. How many sheep are left?",
        stream=True,
        show_full_reasoning=True,
    )
