"""
Fallback Models — Basic
=============================

When the primary model fails (after exhausting its own retries),
fallback models are tried in order until one succeeds.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Basic: pass a list of fallback models directly
# The primary model points to an unreachable server so it will fail
# with a connection error, then the fallback (Claude) handles the request.
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o", base_url="http://localhost:1/v1", retries=0),
    fallback_models=[Claude(id="claude-sonnet-4-20250514")],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the meaning of life?", stream=True)
