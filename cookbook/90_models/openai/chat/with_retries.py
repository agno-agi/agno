"""
Openai With Retries
===================

Cookbook example for `openai/chat/with_retries.py`.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(
        id="gpt-wrong-id",  # Deliberately wrong model ID to trigger retries
        retries=3,
        delay_between_retries=1,
        exponential_backoff=True,
    ),
)
agent.print_response("What is the capital of France?")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
