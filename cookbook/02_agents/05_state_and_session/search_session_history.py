"""
Search Session History
======================

Demonstrates the two-step search-then-read pattern for accessing previous sessions.

The agent gets two tools:
  - search_past_sessions(query?) -- lightweight previews, optional keyword filter
  - read_past_session(session_id) -- full conversation for a specific session

Enable with `search_session_history=True`. Optionally set
`search_past_sessions_limit` to control how many past sessions are searched
(default 20).
"""

import asyncio
import os

from agno.agent.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup -- fresh DB each run
# ---------------------------------------------------------------------------
DB_FILE = "tmp/agent_session_history.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

db = AsyncSqliteDb(db_file=DB_FILE)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    db=db,
    search_session_history=True,
    search_past_sessions_limit=10,
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
async def main() -> None:
    # --- Seed a few sessions with different topics ---
    print("=== Session 1: Space ===")
    await agent.aprint_response(
        "Tell me about black holes",
        session_id="session_space",
        user_id="alice",
    )

    print("\n=== Session 2: Cooking ===")
    await agent.aprint_response(
        "How do I make pasta carbonara?",
        session_id="session_cooking",
        user_id="alice",
    )

    print("\n=== Session 3: Music ===")
    await agent.aprint_response(
        "Who composed the Four Seasons?",
        session_id="session_music",
        user_id="alice",
    )

    # --- Now ask the agent to search and recall ---
    print("\n=== Search: browse all past sessions ===")
    await agent.aprint_response(
        "What topics did we discuss in my previous sessions?",
        session_id="session_recall",
        user_id="alice",
    )

    print("\n=== Search: keyword filter ===")
    await agent.aprint_response(
        "Find my past session where we talked about cooking",
        session_id="session_search",
        user_id="alice",
    )

    # --- Demonstrate user scoping ---
    print("\n=== Different user sees no history ===")
    await agent.aprint_response(
        "What did we discuss before?",
        session_id="bob_session_1",
        user_id="bob",
    )


if __name__ == "__main__":
    asyncio.run(main())
