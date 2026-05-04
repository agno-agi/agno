"""
Synap Integration
=================

Demonstrates Synap-powered persistent memory for an Agno agent.

Unlike simple chat-history stores, Synap runs a full extraction pipeline on every
conversation turn — automatically identifying facts, preferences, episodes, emotions,
and temporal events — and stores them in a dual vector + knowledge-graph backend.
At inference time it retrieves only what is semantically relevant to the current query
(Fast mode: ~50–100 ms; Accurate mode: ~200–500 ms with graph traversal).

Key features:
- Entity resolution: "John", "Mr. Smith", "my manager" → single canonical record
- Four-level scoping: User → Customer → Client → World (strict multi-tenant isolation)
- Async extraction: never adds latency to the user's turn
- Context compaction: long conversations compress into structured summaries

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

# SynapDb extends Agno's InMemoryDb, routing user-memory operations through
# Synap's cloud platform while keeping sessions and traces in-process.
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
        "You are a helpful assistant with access to the user's long-term memory. "
        "You remember facts, preferences, and past interactions across sessions."
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
    # (entity resolution means "Alex" → same canonical record across sessions)
    agent.print_response("What do you know about my dietary restrictions?")

    # Cross-session: same user_id retrieves memories from previous runs
    agent.print_response("Which editor theme should I use?")
