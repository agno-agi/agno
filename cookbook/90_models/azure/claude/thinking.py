"""
Azure AI Foundry Claude Thinking
=================================

Cookbook example for `azure/claude/thinking.py`.
"""

from agno.agent import Agent
from agno.models.azure.claude import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-6",
        max_tokens=2048,
        thinking={"type": "enabled", "budget_tokens": 1024},
    ),
    markdown=True,
)

# Note: String syntax (model="azure-foundry-claude:claude-sonnet-4-5") works for basic usage.
# Use the class syntax above when configuring thinking or other model-specific parameters.

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a very scary 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a very scary 2 sentence horror story", stream=True)
