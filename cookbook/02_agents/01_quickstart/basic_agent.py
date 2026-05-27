"""
Basic Agent
=============================

Basic Agent Quickstart.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Quickstart Agent",
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Say hello and introduce yourself in one sentence.", stream=True
    )
