"""
This example demonstrates how to run a multi-user, multi-session chat.

In this example, we have 3 users and 4 sessions.

User 1 has 2 sessions.
User 2 has 1 session.
User 3 has 1 session.
"""

import asyncio

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

user_1_id = "user_1@example.com"
user_2_id = "user_2@example.com"
user_3_id = "user_3@example.com"

user_1_session_1_id = "user_1_session_1"
user_1_session_2_id = "user_1_session_2"
user_2_session_1_id = "user_2_session_1"
user_3_session_1_id = "user_3_session_1"

chat_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
)


async def run_chat_agent():
    await chat_agent.aprint_response(
        "My name is Mark Gonzales and I like anime and video games.",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )
    await chat_agent.aprint_response(
        "I also enjoy reading manga and playing video games.",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    # Chat with user 1 - Session 2
    await chat_agent.aprint_response(
        "I'm going to the movies tonight.",
        user_id=user_1_id,
        session_id=user_1_session_2_id,
    )

    # Chat with user 2
    await chat_agent.aprint_response(
        "Hi my name is John Doe.", user_id=user_2_id, session_id=user_2_session_1_id
    )
    await chat_agent.aprint_response(
        "I'm planning to hike this weekend.",
        user_id=user_2_id,
        session_id=user_2_session_1_id,
    )

    # Chat with user 3
    await chat_agent.aprint_response(
        "Hi my name is Jane Smith.", user_id=user_3_id, session_id=user_3_session_1_id
    )
    await chat_agent.aprint_response(
        "I'm going to the gym tomorrow.",
        user_id=user_3_id,
        session_id=user_3_session_1_id,
    )

    # Continue the conversation with user 1
    # The agent should take into account all memories of user 1.
    await chat_agent.aprint_response(
        "What do you suggest I do this weekend?",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )


if __name__ == "__main__":
    # Chat with user 1 - Session 1
    asyncio.run(run_chat_agent())

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
