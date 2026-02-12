"""
Anthropic Basic With Timeout
============================

Cookbook example for `anthropic/basic_with_timeout.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Claude(id="claude-sonnet-4-5-20250929", timeout=1.0), markdown=True)

agent.print_response("Share a 2 sentence horror story")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
