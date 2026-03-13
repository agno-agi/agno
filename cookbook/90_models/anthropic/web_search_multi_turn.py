"""
Anthropic Web Search Multi-Turn
================================

Multi-turn web search: searches for a topic, then asks a follow-up
that depends on the search results from the previous turn.
Requires server tool blocks to be preserved in conversation history.

Run: .venvs/demo/bin/python cookbook/90_models/anthropic/web_search_multi_turn.py
"""

import asyncio

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 3,
        }
    ],
    db=InMemoryDb(),
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Search the web for the latest Anthropic news")
    agent.print_response("Search for more details about the first topic you mentioned")

    # --- Sync + Streaming ---
    agent.session_id = None
    agent.print_response("Search the web for the latest Anthropic news", stream=True)
    agent.print_response(
        "Search for more details about the first topic you mentioned",
        stream=True,
    )

    # --- Async ---
    agent.session_id = None

    async def run_async():
        await agent.aprint_response("Search the web for the latest Anthropic news")
        await agent.aprint_response("Search for more details about the first topic you mentioned")

    asyncio.run(run_async())

    # --- Async + Streaming ---
    agent.session_id = None

    async def run_async_stream():
        await agent.aprint_response(
            "Search the web for the latest Anthropic news",
            stream=True,
        )
        await agent.aprint_response(
            "Search for more details about the first topic you mentioned",
            stream=True,
        )

    asyncio.run(run_async_stream())
