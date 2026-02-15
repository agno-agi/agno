"""
Session Summary
=============================

Demonstrates session summary creation, context reuse, and async summary retrieval.
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
sync_db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
sync_db = PostgresDb(db_url=sync_db_url, session_table="sessions")

async_db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"
async_db = AsyncPostgresDb(db_url=async_db_url, session_table="sessions")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
sync_agent = Agent(model=OpenAIResponses(id="gpt-5-mini"))
async_agent = Agent(model=OpenAIResponses(id="gpt-5.2"))

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
summary_team = Team(
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[sync_agent],
    db=sync_db,
    enable_session_summaries=True,
)

context_summary_team = Team(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=sync_db,
    session_id="session_summary",
    add_session_summary_to_context=True,
    members=[sync_agent],
)

async_summary_team = Team(
    model=OpenAIResponses(id="gpt-5.2"),
    members=[async_agent],
    db=async_db,
    session_id="async_team_session_summary",
    enable_session_summaries=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def run_async_summary_demo() -> None:
    print("Running first interaction...")
    await async_summary_team.aprint_response(
        "Hi my name is Jane and I work as a software engineer"
    )

    print("\nRunning second interaction...")
    await async_summary_team.aprint_response(
        "I enjoy coding in Python and building AI applications"
    )

    print("\nRetrieving session summary asynchronously...")
    summary = await async_summary_team.aget_session_summary(
        session_id="async_team_session_summary"
    )

    if summary:
        print(f"\nSession Summary: {summary.summary}")
        if summary.topics:
            print(f"Topics: {', '.join(summary.topics)}")
    else:
        print("No session summary found")


if __name__ == "__main__":
    summary_team.print_response("Hi my name is John and I live in New York")
    summary_team.print_response("I like to play basketball and hike in the mountains")

    summary_team.print_response(
        "My name is John Doe and I like to hike in the mountains on weekends.",
    )

    context_summary_team.print_response("I also like to play basketball.")

    asyncio.run(run_async_summary_demo())
