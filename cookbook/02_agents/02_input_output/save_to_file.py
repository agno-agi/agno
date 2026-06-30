"""
Save To File
=============================

Save agent responses to a file automatically.
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    save_response_to_file="tmp/agent_output.md",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    os.makedirs("tmp", exist_ok=True)
    agent.print_response(
        "Write a brief guide on Python virtual environments.",
        stream=True,
    )
    print(f"\nResponse saved to: {agent.save_response_to_file}")
