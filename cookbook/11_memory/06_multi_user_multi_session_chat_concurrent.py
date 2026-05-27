"""
Concurrent Multi-User Multi-Session Chat
========================================

This example runs multiple user conversations concurrently while persisting
memory per user and session.
"""

import asyncio

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

user_1_id = "user_1@example.com"
user_2_id = "user_2@example.com"
user_3_id = "user_3@example.com"

user_1_session_1_id = "user_1_session_1"
user_1_session_2_id = "user_1_session_2"
user_2_session_1_id = "user_2_session_1"
user_3_session_1_id = "user_3_session_1"

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
chat_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    update_memory_on_run=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def user_1_conversation() -> None:
    await chat_agent.arun(
        "My name is Mark Gonzales and I like anime and video games.",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )
    await chat_agent.arun(
        "I also enjoy reading manga and playing video games.",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    await chat_agent.arun(
        "I'm going to the movies tonight.",
        user_id=user_1_id,
        session_id=user_1_session_2_id,
    )

    await chat_agent.arun(
        "What do you suggest I do this weekend?",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    print("User 1 Done")


async def user_2_conversation() -> None:
    await chat_agent.arun(
        "Hi my name is John Doe.", user_id=user_2_id, session_id=user_2_session_1_id
    )
    await chat_agent.arun(
        "I'm planning to hike this weekend.",
        user_id=user_2_id,
        session_id=user_2_session_1_id,
    )
    print("User 2 Done")


async def user_3_conversation() -> None:
    await chat_agent.arun(
        "Hi my name is Jane Smith.", user_id=user_3_id, session_id=user_3_session_1_id
    )
    await chat_agent.arun(
        "I'm going to the gym tomorrow.",
        user_id=user_3_id,
        session_id=user_3_session_1_id,
    )
    print("User 3 Done")


async def run_concurrent_chat_agent() -> None:
    await asyncio.gather(
        user_1_conversation(), user_2_conversation(), user_3_conversation()
    )


if __name__ == "__main__":
    asyncio.run(run_concurrent_chat_agent())

    user_1_memories = chat_agent.get_user_memories(user_id=user_1_id)
    print("User 1's memories:")
    assert user_1_memories is not None
    for i, m in enumerate(user_1_memories):
        print(f"{i}: {m.memory}")

    user_2_memories = chat_agent.get_user_memories(user_id=user_2_id)
    print("User 2's memories:")
    assert user_2_memories is not None
    for i, m in enumerate(user_2_memories):
        print(f"{i}: {m.memory}")

    user_3_memories = chat_agent.get_user_memories(user_id=user_3_id)
    print("User 3's memories:")
    assert user_3_memories is not None
    for i, m in enumerate(user_3_memories):
        print(f"{i}: {m.memory}")
