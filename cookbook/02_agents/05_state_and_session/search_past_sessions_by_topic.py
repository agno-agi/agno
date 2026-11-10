"""
Search Past Sessions By Topic
=============================

Demonstrates finding a past session by what was discussed, not by recency, and
reading only part of it.

search_past_sessions accepts optional filters:
  - query -- matched against session names, summaries and what was said in each run
  - since -- only sessions active on or after an ISO 8601 date or time
  - until -- only sessions started on or before an ISO 8601 date or time

read_past_session accepts `start` (negative counts from the end) and `num_runs`,
so the agent can read the last few runs of a long session.

Both tools only see sessions that belong to this agent.
"""

import asyncio
import os

from agno.agent.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup -- fresh DB each run
# ---------------------------------------------------------------------------
DB_FILE = "tmp/agent_session_topics.db"
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

db = AsyncSqliteDb(db_file=DB_FILE)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    id="support-agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    search_past_sessions=True,
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
async def main() -> None:
    print("=== Session 1: Billing export ===")
    await agent.arun(
        "Our nightly billing export to S3 failed with an access denied error.",
        session_id="session_billing",
        user_id="alice",
    )
    await agent.arun(
        "We rotated the IAM role yesterday. Could that be it?",
        session_id="session_billing",
        user_id="alice",
    )

    print("=== Session 2: Onboarding ===")
    await agent.arun(
        "Draft a short onboarding checklist for a new support engineer.",
        session_id="session_onboarding",
        user_id="alice",
    )

    print("\n=== Search by topic ===")
    await agent.aprint_response(
        "Find the earlier conversation about the IAM role and tell me what we suspected.",
        session_id="session_recall",
        user_id="alice",
    )

    print("\n=== Read only the end of a session ===")
    await agent.aprint_response(
        "Read only the last run of the billing export conversation and quote my question.",
        session_id="session_tail",
        user_id="alice",
    )


if __name__ == "__main__":
    asyncio.run(main())
