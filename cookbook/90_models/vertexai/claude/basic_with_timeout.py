"""
Vertexai Basic With Timeout
===========================

Cookbook example for `vertexai/claude/basic_with_timeout.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.vertexai.claude import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Claude(id="claude-sonnet-4@20250514", timeout=5), markdown=True)

agent.print_response("Share a 2 sentence horror story")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
