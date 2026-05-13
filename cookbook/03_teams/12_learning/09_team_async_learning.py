"""
Team Learning: Async Mode
=========================
Demonstrates Team learning with async database operations.

Uses AsyncPostgresDb for non-blocking database access.
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

db = AsyncPostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Research topics thoroughly.",
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Create concise summaries.",
)

team = Team(
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, summarizer],
    db=db,
    learning=True,
    markdown=True,
)


async def main():
    user_id = "async_test@example.com"

    print("\n" + "=" * 60)
    print("SESSION 1: Async learning extraction")
    print("=" * 60 + "\n")

    await team.aprint_response(
        "I'm a backend engineer interested in distributed systems. "
        "I prefer deep technical content with architecture diagrams.",
        user_id=user_id,
        session_id="async_session_1",
        stream=True,
    )

    lm = team.learning_machine
    print("\n--- Extracted Profile (Async) ---")
    lm.user_profile_store.print(user_id=user_id)

    print("\n" + "=" * 60)
    print("SESSION 2: Async recall in new session")
    print("=" * 60 + "\n")

    await team.aprint_response(
        "Based on my background, explain consensus algorithms.",
        user_id=user_id,
        session_id="async_session_2",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
