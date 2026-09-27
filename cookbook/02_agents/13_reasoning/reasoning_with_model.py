"""
Reasoning With Model
=============================

Use a separate native reasoning model (o1, o3, DeepSeek-R1, etc.) for thinking.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6"),
    # Use a native reasoning model for the thinking step
    reasoning_model=OpenAIResponses(id="o3-mini"),
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
