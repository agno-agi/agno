"""
This example demonstrates how to use the async `aget_session_summary()` method
to retrieve session summaries in async workflows.

Start the postgres db locally on Docker by running: cookbook/scripts/run_pgvector.sh
"""

import asyncio

from agno.agent.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"

db = AsyncPostgresDb(db_url=db_url, session_table="sessions")


async def main():
    # Create an agent with session summaries enabled
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=db,
        session_id="async_session_summary",
        enable_session_summaries=True,
    )

    # Run some interactions
    print("Running first interaction...")
    await agent.aprint_response("Hi my name is John and I live in New York")

    print("\nRunning second interaction...")
    await agent.aprint_response("I like to play basketball and hike in the mountains")

    # Use the async method to get the session summary
    print("\nRetrieving session summary asynchronously...")
    summary = await agent.aget_session_summary(session_id="async_session_summary")

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
