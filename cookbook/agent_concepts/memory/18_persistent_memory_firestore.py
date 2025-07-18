"""
This example shows how to run a multi-user, multi-session chat concurrently with Firestore.

In this example, we have 3 users and 4 sessions.

User 1 has 2 sessions.
User 2 has 1 session.
User 3 has 1 session.

Steps:
1. Ensure you have firestore enabled in your gcloud project. See: https://cloud.google.com/firestore/docs/create-database-server-client-library
2. Run: `pip install openai google-cloud-firestore agno` to install dependencies
3. Set up authentication:
   - Option 1: Run `gcloud auth application-default login`
   - Option 2: Set GOOGLE_APPLICATION_CREDENTIALS environment variable to your service account key
   - Option 3: If running on GCP, it will use the default service account
4. Make sure your project has Firestore API enabled
"""

import asyncio

from agno.agent.agent import Agent
from agno.memory.v2.db.firestore import FirestoreMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.storage.firestore import FirestoreStorage

agent_storage = FirestoreStorage(
    db_name="memory",
    project_id="forward-vial-458917-s8",
    collection_name="agno_sessions",
)
memory_db = FirestoreMemoryDb(
    db_name="memory", project_id="forward-vial-458917-s8", collection_name="agno_memory"
)

memory = Memory(model=Claude(id="claude-3-5-sonnet-20241022"), db=memory_db)

# Reset the memory for this example
memory.clear()

user_1_id = "user_1@example.com"
user_2_id = "user_2@example.com"
user_3_id = "user_3@example.com"

user_1_session_1_id = "user_1_session_1"
user_1_session_2_id = "user_1_session_2"
user_2_session_1_id = "user_2_session_1"
user_3_session_1_id = "user_3_session_1"

chat_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    storage=agent_storage,
    memory=memory,
    enable_user_memories=True,
)


async def user_1_conversation():
    """Handle conversation with user 1 across multiple sessions"""
    # User 1 - Session 1
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

    # User 1 - Session 2
    await chat_agent.arun(
        "I'm going to the movies tonight.",
        user_id=user_1_id,
        session_id=user_1_session_2_id,
    )

    # Continue the conversation in session 1
    await chat_agent.arun(
        "What do you suggest I do this weekend?",
        user_id=user_1_id,
        session_id=user_1_session_1_id,
    )

    print("User 1 Done")


async def user_2_conversation():
    """Handle conversation with user 2"""
    await chat_agent.arun(
        "Hi my name is John Doe.", user_id=user_2_id, session_id=user_2_session_1_id
    )
    await chat_agent.arun(
        "I'm planning to hike this weekend.",
        user_id=user_2_id,
        session_id=user_2_session_1_id,
    )
    print("User 2 Done")


async def user_3_conversation():
    """Handle conversation with user 3"""
    await chat_agent.arun(
        "Hi my name is Jane Smith.", user_id=user_3_id, session_id=user_3_session_1_id
    )
    await chat_agent.arun(
        "I'm going to the gym tomorrow.",
        user_id=user_3_id,
        session_id=user_3_session_1_id,
    )
    print("User 3 Done")


async def run_concurrent_chat_agent():
    """Run all user conversations concurrently"""
    await asyncio.gather(
        user_1_conversation(), user_2_conversation(), user_3_conversation()
    )


if __name__ == "__main__":
    # Run all conversations concurrently
    asyncio.run(run_concurrent_chat_agent())

    user_1_memories = memory.get_user_memories(user_id=user_1_id)
    print("User 1's memories:")
    for i, m in enumerate(user_1_memories):
        print(f"{i}: {m.memory}")

    user_2_memories = memory.get_user_memories(user_id=user_2_id)
    print("User 2's memories:")
    for i, m in enumerate(user_2_memories):
        print(f"{i}: {m.memory}")

    user_3_memories = memory.get_user_memories(user_id=user_3_id)
    print("User 3's memories:")
    for i, m in enumerate(user_3_memories):
        print(f"{i}: {m.memory}")
