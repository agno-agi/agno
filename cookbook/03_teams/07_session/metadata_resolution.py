"""
Metadata Resolution
=============================

Demonstrates the three-layer metadata resolution for Teams:
  team.metadata < session.metadata < call-site metadata

Session-stored metadata overrides team defaults, and call-site
metadata overrides both. This works for both sync and async runs.
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.session.team import TeamSession
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = InMemoryDb()

# Pre-seed a session with metadata (simulates a returning user)
session = TeamSession(
    session_id="demo-session",
    team_id="metadata-demo-team",
    metadata={
        "user_tier": "premium",  # Will override team's "free"
        "session_pref": "dark_mode",  # Session-only key
    },
    created_at=int(time.time()),
)
db.upsert_session(session)

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
helper_agent = Agent(name="helper", model=OpenAIResponses(id="gpt-5-mini"))

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    id="metadata-demo-team",
    members=[helper_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    metadata={
        "user_tier": "free",  # Will be overridden by session
        "team_env": "production",  # Team-only key
    },
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def run_async_demo() -> None:
    print("\n=== Async run with call-site override ===")
    result = await team.arun(
        input="Say 'async test'",
        metadata={"user_tier": "vip"},
    )
    print(f"Metadata: {result.metadata}")
    print(f"  user_tier = '{result.metadata['user_tier']}' (call-site wins)")
    print(f"  team_env = '{result.metadata['team_env']}' (from team)")


if __name__ == "__main__":
    # Session metadata overrides team metadata
    print("=== Session overrides team (sync) ===")
    result1 = team.run(input="Say 'test1'", session_id="demo-session")
    print(f"Metadata: {result1.metadata}")
    print(f"  user_tier = '{result1.metadata['user_tier']}' (session wins over team)")

    # Call-site metadata overrides both
    print("\n=== Call-site overrides all (sync) ===")
    result2 = team.run(
        input="Say 'test2'",
        session_id="demo-session",
        metadata={"user_tier": "enterprise", "request_id": "req-123"},
    )
    print(f"Metadata: {result2.metadata}")
    print(f"  user_tier = '{result2.metadata['user_tier']}' (call-site wins)")

    # Async run
    asyncio.run(run_async_demo())

    # New session uses team defaults
    print("\n=== New session uses team defaults ===")
    result4 = team.run(input="Say 'test4'", session_id="new-session")
    print(f"Metadata: {result4.metadata}")
    print(f"  user_tier = '{result4.metadata['user_tier']}' (team default)")

    print("\n" + "=" * 50)
    print("Resolution order: team < session < call-site")
    print("=" * 50)
