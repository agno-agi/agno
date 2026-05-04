"""
Synap Integration
=================

Demonstrates Synap-powered persistent memory for an Agno agent.

Synap is a managed memory layer for AI agents. It automatically extracts facts,
preferences, episodes, emotions, and temporal events from conversations and retrieves
only what is relevant to the current query — so agents remember users across sessions
without any manual bookkeeping.

Install:
    pip install maximem-synap-agno

Docs: https://docs.maximem.ai/integrations/agno
Dashboard: https://synap.maximem.ai
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from maximem_synap import MaximemSynapSDK
from synap_agno import SynapDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
sdk = MaximemSynapSDK(api_key=os.environ["SYNAP_API_KEY"])

# SynapDb extends Agno's InMemoryDb and routes user-memory operations through
# Synap while keeping sessions and traces in-process.
db = SynapDb(
    sdk=sdk,
    user_id="agno-demo-user",
    customer_id="agno-demo-customer",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(),
    db=db,
    memory=True,
    description=(
        "You are a helpful assistant. You remember facts and preferences "
        "about the user across sessions."
    ),
)

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # First turn — Synap extracts facts and preferences in the background
    agent.print_response(
        "My name is Alex. I'm a software engineer who loves Python "
        "and is allergic to peanuts. I prefer dark mode in all my tools."
    )

    # Later turn — Synap retrieves the relevant facts automatically
    agent.print_response("What do you know about my dietary restrictions?")

    # Cross-session: same user_id retrieves memories from previous runs
    agent.print_response("Which editor theme should I use?")
