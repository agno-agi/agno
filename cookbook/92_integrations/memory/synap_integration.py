"""
Synap Integration
=================

Demonstrates Synap-powered persistent memory for an Agno agent.

Synap is a managed memory layer for AI agents. It automatically extracts facts,
preferences, episodes, emotions, and temporal events from conversations and retrieves
only what is relevant to the current query — so agents remember users across sessions
without any manual bookkeeping.

Setup
-----
1. Install dependencies::

       pip install maximem-synap-agno openai

2. Set environment variables::

       export SYNAP_API_KEY=<your-key>   # get a free key at https://synap.maximem.ai
       export OPENAI_API_KEY=<your-key>  # used by OpenAIChat() in this example

3. Run::

       python synap_integration.py

Docs: https://docs.maximem.ai/integrations/agno
Dashboard: https://synap.maximem.ai
Open source: https://github.com/maximem-ai/maximem_synap_sdk/tree/main/packages/integrations
"""

import asyncio
import os
import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from maximem_synap import MaximemSynapSDK
from synap_agno import SynapDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
sdk = MaximemSynapSDK(api_key=os.environ["SYNAP_API_KEY"])
asyncio.run(sdk.initialize())

# SynapDb extends Agno's InMemoryDb and routes user-memory operations through
# Synap while keeping sessions and traces in-process.
db = SynapDb(
    sdk=sdk,
    customer_id="agno-demo-customer",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(),
    db=db,
    user_id="agno-demo-user",
    enable_agentic_memory=True,
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

    # Synap ingests memories asynchronously; allow a moment for extraction
    # before querying so the facts are available for retrieval.
    time.sleep(5)

    # Second turn — Synap retrieves the relevant facts automatically
    agent.print_response("What do you know about my dietary restrictions?")

    # Cross-session: create a fresh agent instance with the same user_id to
    # demonstrate that memories persist across independent agent instances.
    fresh_agent = Agent(
        model=OpenAIChat(),
        db=SynapDb(
            sdk=sdk,
            customer_id="agno-demo-customer",
        ),
        user_id="agno-demo-user",
        enable_agentic_memory=True,
        description="You are a helpful assistant with access to the user's memory.",
    )
    fresh_agent.print_response("Which editor theme should I use?")
