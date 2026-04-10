"""
Background Mode
===============

Background mode enables long-running tasks on reasoning models like GPT-5.4
without worrying about timeouts or connectivity issues. The API returns
immediately and Agno polls for the result automatically.

Requires: openai>=2.0.0
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent with background mode enabled
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.4",
        background=True,
        background_poll_interval=2.0,  # seconds between polls (default)
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Explain the history of quantum computing in detail")
