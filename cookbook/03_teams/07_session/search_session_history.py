"""
Search Session History
======================

Demonstrates searching prior sessions with user-scoped history access.
"""

import asyncio
import os

from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if os.path.exists("tmp/data.db"):
    os.remove("tmp/data.db")

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    model=OpenAIResponses(id="gpt-5.2"),
    members=[],
    db=AsyncSqliteDb(db_file="tmp/data.db"),
    search_session_history=True,
    num_history_sessions=2,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def main() -> None:
    print("=== User 1 Sessions ===")
    await team.aprint_response(
        "What is the capital of South Africa?",
        session_id="user1_session_1",
        user_id="user_1",
    )
    await team.aprint_response(
        "What is the capital of China?",
        session_id="user1_session_2",
        user_id="user_1",
    )
    await team.aprint_response(
        "What is the capital of France?",
        session_id="user1_session_3",
        user_id="user_1",
    )

    print("\n=== User 2 Sessions ===")
    await team.aprint_response(
        "What is the population of India?",
        session_id="user2_session_1",
        user_id="user_2",
    )
    await team.aprint_response(
        "What is the currency of Japan?",
        session_id="user2_session_2",
        user_id="user_2",
    )

    print("\n=== Testing Session History Search ===")
    print(
        "User 1 asking about previous conversations (should only see capitals, not population/currency):"
    )
    await team.aprint_response(
        "What did I discuss in my previous conversations?",
        session_id="user1_session_4",
        user_id="user_1",
    )

    print(
        "\nUser 2 asking about previous conversations (should only see population/currency, not capitals):"
    )
    await team.aprint_response(
        "What did I discuss in my previous conversations?",
        session_id="user2_session_3",
        user_id="user_2",
    )


if __name__ == "__main__":
    asyncio.run(main())
