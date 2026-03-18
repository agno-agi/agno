"""
Agent With Persistent Memory
============================

This example shows how to use persistent memory with an Agent.
After each run, user memories are created or updated.
"""

import asyncio
from uuid import uuid4

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    db.clear_memories()

    session_id = str(uuid4())
    john_doe_id = "john_doe@example.com"

    asyncio.run(
        agent.aprint_response(
            "My name is John Doe and I like to hike in the mountains on weekends.",
            stream=True,
            user_id=john_doe_id,
            session_id=session_id,
        )
    )

    agent.print_response(
        "What are my hobbies?", stream=True, user_id=john_doe_id, session_id=session_id
    )

    memories = agent.get_user_memories(user_id=john_doe_id)
    print("John Doe's memories:")
    pprint(memories)

    agent.print_response(
        "Ok i dont like hiking anymore, i like to play soccer instead.",
        stream=True,
        user_id=john_doe_id,
        session_id=session_id,
    )

    memories = agent.get_user_memories(user_id=john_doe_id)
    print("John Doe's memories:")
    pprint(memories)
