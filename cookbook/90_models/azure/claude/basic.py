"""
Azure AI Foundry Claude Basic
==============================

Cookbook example for `azure/claude/basic.py`.

Set the following environment variables:
- ANTHROPIC_FOUNDRY_API_KEY: Your Azure AI Foundry API key
- ANTHROPIC_FOUNDRY_RESOURCE: Your Azure resource name
"""

import asyncio

from agno.agent import Agent
from agno.models.azure.claude import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Claude(id="claude-sonnet-4-6"), markdown=True)

# String syntax alternative:
# agent = Agent(model="azure-foundry-claude:claude-sonnet-4-5", markdown=True)

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
