"""
Vertexai Thinking
=================

Cookbook example for `vertexai/claude/thinking.py`.
"""

from agno.agent import Agent
from agno.models.vertexai.claude import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(
        id="claude-sonnet-4@20250514",
        max_tokens=2048,
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a very scary 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a very scary 2 sentence horror story", stream=True)
