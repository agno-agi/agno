"""
Copilot Basic
=============

Basic cookbook example for GitHub Copilot model provider.

Set the GITHUB_COPILOT_TOKEN environment variable or pass github_token directly.

Both the class-based and string-based syntax are shown below.
"""

import asyncio

from agno.agent import Agent
from agno.models.copilot import CopilotChat

# ---------------------------------------------------------------------------
# Create Agent  (class syntax)
# ---------------------------------------------------------------------------

agent = Agent(
    model=CopilotChat(id="gpt-4.1"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Or use the string syntax:
#   agent = Agent(model="copilot:gpt-4.1", markdown=True)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
