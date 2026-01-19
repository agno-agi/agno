import asyncio
import os

from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team

# Remove the tmp db file before running the script
if os.path.exists("tmp/data.db"):
    os.remove("tmp/data.db")

# Create agents for different users to demonstrate user-specific session history
team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[],  # No members, just for the demo
    db=AsyncSqliteDb(db_file="tmp/data.db"),
    search_session_history=True,  # allow searching previous sessions
    num_history_sessions=2,  # only include the last 2 sessions in the search to avoid context length issues
)


async def main():
    # User 1 sessions
    print("=== User 1 Sessions ===")
    await team.aprint_response(
        "What is the capital of South Africa?",
        session_id="user1_session_1",
        user_id="user_1",
    )
    await team.aprint_response(
        "What is the capital of China?", session_id="user1_session_2", user_id="user_1"
    )
    await team.aprint_response(
        "What is the capital of France?", session_id="user1_session_3", user_id="user_1"
    )

    # User 2 sessions
    print("\n=== User 2 Sessions ===")
    await team.aprint_response(
        "What is the population of India?",
        session_id="user2_session_1",
        user_id="user_2",
    )
    await team.aprint_response(
        "What is the currency of Japan?", session_id="user2_session_2", user_id="user_2"
    )

    # Now test session history search - each user should only see their own sessions
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
