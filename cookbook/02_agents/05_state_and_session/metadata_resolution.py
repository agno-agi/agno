"""
Metadata Resolution
=============================

Demonstrates the three-layer metadata resolution for Agents:
  agent.metadata < session.metadata < call-site metadata

Session-stored metadata overrides agent defaults, and call-site
metadata overrides both. This works for both sync and async runs.
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.session.agent import AgentSession

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = InMemoryDb()

# Pre-seed a session with metadata (simulates a returning user)
session = AgentSession(
    session_id="demo-session",
    agent_id="metadata-demo-agent",
    metadata={
        "user_tier": "premium",  # Will override agent's "free"
        "session_pref": "dark_mode",  # Session-only key
    },
    created_at=int(time.time()),
)
db.upsert_session(session)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="metadata-demo-agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    metadata={
        "user_tier": "free",  # Will be overridden by session
        "agent_env": "production",  # Agent-only key
    },
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def run_async_demo() -> None:
    print("\n=== Async run with all three layers ===")
    result = await agent.arun(
        input="Say 'async test'",
        session_id="demo-session",
        metadata={"user_tier": "vip"},
    )
    print(f"Metadata: {result.metadata}")
    print(f"  user_tier = '{result.metadata['user_tier']}' (call-site wins)")
    print(f"  session_pref = '{result.metadata['session_pref']}' (from session)")
    print(f"  agent_env = '{result.metadata['agent_env']}' (from agent)")


if __name__ == "__main__":
    # Session metadata overrides agent metadata
    print("=== Session overrides agent (sync) ===")
    result1 = agent.run(input="Say 'test1'", session_id="demo-session")
    print(f"Metadata: {result1.metadata}")
    print(f"  user_tier = '{result1.metadata['user_tier']}' (session wins over agent)")

    # Call-site metadata overrides both
    print("\n=== Call-site overrides all (sync) ===")
    result2 = agent.run(
        input="Say 'test2'",
        session_id="demo-session",
        metadata={"user_tier": "enterprise", "request_id": "req-123"},
    )
    print(f"Metadata: {result2.metadata}")
    print(f"  user_tier = '{result2.metadata['user_tier']}' (call-site wins)")

    # Async run
    asyncio.run(run_async_demo())

    # New session uses agent defaults
    print("\n=== New session uses agent defaults ===")
    result4 = agent.run(input="Say 'test4'", session_id="new-session")
    print(f"Metadata: {result4.metadata}")
    print(f"  user_tier = '{result4.metadata['user_tier']}' (agent default)")

    print("\n" + "=" * 50)
    print("Resolution order: agent < session < call-site")
    print("=" * 50)
