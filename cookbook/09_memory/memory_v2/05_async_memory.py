"""
Memory V2 Async - Concurrent Users with Personalized Memory
============================================================
This example shows async support for Memory V2 with multiple concurrent users.
Each user has isolated memory, enabling personalized responses.

Different from sync examples, this uses AsyncSqliteDb and asyncio.gather
to handle multiple users concurrently.

Key concepts:
- AsyncSqliteDb: Async database for non-blocking I/O
- asyncio.gather: Run multiple user conversations concurrently
- Memory isolation: Each user_id has separate memory

Requirements:
    pip install aiosqlite
"""

import asyncio
import json

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = AsyncSqliteDb(db_file="tmp/async_user_memory.db")

# ============================================================================
# User Configuration
# ============================================================================
alex_id = "alex"
jordan_id = "jordan"

# ============================================================================
# Create the Agent
# ============================================================================
agent = Agent(
    name="Async Memory Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    enable_agentic_memory_v2=True,
    markdown=True,
)


# ============================================================================
# User Conversations
# ============================================================================
async def alex_conversation():
    """Backend developer with Python focus."""
    await agent.arun(
        "Hi! I'm Alex, a backend developer. I work primarily with Python and FastAPI.",
        user_id=alex_id,
    )
    await agent.arun(
        "I always use type hints in my Python code. Please include them in examples.",
        user_id=alex_id,
    )
    await agent.arun(
        "Please remember that I prefer async/await patterns over threading.",
        user_id=alex_id,
    )


async def jordan_conversation():
    """Frontend developer with React focus."""
    await agent.arun(
        "Hey! I'm Jordan, a frontend developer. I specialize in React and TypeScript.",
        user_id=jordan_id,
    )
    await agent.arun(
        "I prefer functional components with hooks over class components.",
        user_id=jordan_id,
    )
    await agent.arun(
        "Remember that I like seeing accessibility considerations in UI code.",
        user_id=jordan_id,
    )


# ============================================================================
# Run the Agent
# ============================================================================
async def main():
    # Run both conversations concurrently
    await asyncio.gather(alex_conversation(), jordan_conversation())

    # View each user's memory
    print("\n" + "=" * 60)
    print("Alex's Memory")
    print("=" * 60)
    alex_profile = await agent.aget_user_memory_v2(alex_id)
    if alex_profile:
        print_json(json.dumps(alex_profile.to_dict()))

    print("\n" + "=" * 60)
    print("Jordan's Memory")
    print("=" * 60)
    jordan_profile = await agent.aget_user_memory_v2(jordan_id)
    if jordan_profile:
        print_json(json.dumps(jordan_profile.to_dict()))

    # Same question, personalized responses
    print("\n" + "=" * 60)
    print("Personalized Responses")
    print("=" * 60)
    await agent.aprint_response(
        "What's the best way to handle API errors?", user_id=alex_id, stream=True
    )
    await agent.aprint_response(
        "What's the best way to handle API errors?", user_id=jordan_id, stream=True
    )


if __name__ == "__main__":
    asyncio.run(main())

# ============================================================================
# More Examples
# ============================================================================
"""
Async methods available:

- agent.arun(): Async version of run()
- agent.aprint_response(): Async version of print_response()
- agent.aget_user_memory_v2(): Async version of get_user_memory_v2()

Database options:

- AsyncSqliteDb: Local async SQLite
- AsyncPostgresDb: Production async PostgreSQL

Use asyncio.gather() to run multiple operations concurrently
when they don't depend on each other.
"""
