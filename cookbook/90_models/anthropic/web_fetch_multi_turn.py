"""
Anthropic Web Fetch Multi-Turn
==============================

Multi-turn web fetch: fetches a page, then follows a discovered link.
Requires server tool blocks to be preserved in conversation history.

Run: .venvs/demo/bin/python cookbook/90_models/anthropic/web_fetch_multi_turn.py
"""

import asyncio

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        {
            "type": "web_fetch_20250910",
            "name": "web_fetch",
            "max_uses": 3,
        }
    ],
    db=InMemoryDb(),
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Sync ---
    # Turn 1: Fetch a page and list links
    agent.print_response(
        "Fetch https://example.com and list any links you find on the page"
    )
    # Turn 2: Follow a discovered link (URL only exists in server tool history)
    agent.print_response(
        "Now fetch the first link you listed and summarize that page"
    )

    # --- Sync + Streaming ---
    agent.session_id = None
    agent.print_response(
        "Fetch https://example.com and list any links you find on the page",
        stream=True,
    )
    agent.print_response(
        "Now fetch the first link you listed and summarize that page",
        stream=True,
    )

    # --- Async ---
    agent.session_id = None

    async def run_async():
        await agent.aprint_response(
            "Fetch https://example.com and list any links you find on the page"
        )
        await agent.aprint_response(
            "Now fetch the first link you listed and summarize that page"
        )

    asyncio.run(run_async())

    # --- Async + Streaming ---
    agent.session_id = None

    async def run_async_stream():
        await agent.aprint_response(
            "Fetch https://example.com and list any links you find on the page",
            stream=True,
        )
        await agent.aprint_response(
            "Now fetch the first link you listed and summarize that page",
            stream=True,
        )

    asyncio.run(run_async_stream())
