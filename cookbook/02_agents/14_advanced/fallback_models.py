"""
Fallback Models
=============================

Example demonstrating how to configure fallback models for an Agent.

When the primary model fails (after exhausting its own retries),
fallback models are tried in order until one succeeds.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Basic: pass a list of fallback models directly
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    fallback_models=[Claude(id="claude-sonnet-4-20250514")],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the meaning of life?", stream=True)
