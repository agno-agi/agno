"""
This example demonstrates how to use the async `aget_session_summary()` method
to retrieve session summaries from teams in async workflows.

Start the postgres db locally on Docker by running: cookbook/scripts/run_pgvector.sh
"""

import asyncio

from agno.agent.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"

db = AsyncPostgresDb(db_url=db_url, session_table="sessions")


async def main():
    # Create an agent to be part of the team
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    # Create a team with session summaries enabled
    team = Team(
        model=OpenAIChat(id="gpt-4o-mini"),
        members=[agent],
        db=db,
        session_id="async_team_session_summary",
        enable_session_summaries=True,
    )

    # Run some interactions
    print("Running first interaction...")
    await team.aprint_response("Hi my name is Jane and I work as a software engineer")

    print("\nRunning second interaction...")
    await team.aprint_response("I enjoy coding in Python and building AI applications")

    # Use the async method to get the session summary
    print("\nRetrieving session summary asynchronously...")
    summary = await team.aget_session_summary(session_id="async_team_session_summary")

    if summary:
        print(f"\nSession Summary: {summary.summary}")
        if summary.topics:
            print(f"Topics: {', '.join(summary.topics)}")
    else:
        print(
            "No session summary found (summaries are created after multiple interactions)"
        )


if __name__ == "__main__":
    asyncio.run(main())
