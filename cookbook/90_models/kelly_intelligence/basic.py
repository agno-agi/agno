"""
Kelly Intelligence Basic
========================

Cookbook example for `kelly_intelligence/basic.py`.

Kelly Intelligence is an OpenAI-compatible API with a built-in
162,000-word vocabulary RAG layer, operated by Lesson of the Day, PBC.

Set the KELLY_API_KEY environment variable before running:

    export KELLY_API_KEY="your-key-from-api.thedailylesson.com"
"""

import asyncio

from agno.agent import Agent
from agno.models.kelly_intelligence import KellyIntelligence

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=KellyIntelligence(id="kelly-haiku"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "Define the word 'ephemeral' for an intermediate English learner."
    )

    # --- Sync + Streaming ---
    agent.print_response(
        "Define the word 'ephemeral' for an intermediate English learner.", stream=True
    )

    # --- Async ---
    asyncio.run(
        agent.aprint_response(
            "Define the word 'ephemeral' for an intermediate English learner."
        )
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Define the word 'ephemeral' for an intermediate English learner.",
            stream=True,
        )
    )
