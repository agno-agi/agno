"""
Incognito Chat
==============

This example shows how to run a single turn without any user-keyed context.

Passing use_user_context=False makes the run incognito: nothing keyed to the
user is read or written. User memories are neither injected into the prompt nor
created from the conversation, the past-session search tools are not registered,
and the user-scoped learning stores are skipped.

The run itself is still saved to the session. Incognito governs what the agent
knows about the user, not whether the conversation is stored.
"""

import asyncio
from uuid import uuid4

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
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
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    update_memory_on_run=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    db.clear_memories()

    john_doe_id = "john_doe@example.com"

    # A normal run: the agent learns about the user and remembers it.
    asyncio.run(
        agent.aprint_response(
            "My name is John Doe and I like to hike in the mountains on weekends.",
            stream=True,
            user_id=john_doe_id,
            session_id=str(uuid4()),
        )
    )

    memories_after_normal_run = agent.get_user_memories(user_id=john_doe_id)
    print("Memories after the normal run:")
    pprint(memories_after_normal_run)

    # An incognito run: the agent cannot see the memory above, and nothing said
    # here is written back to it.
    agent.print_response(
        "I am also thinking about taking up skydiving. What are my hobbies?",
        stream=True,
        user_id=john_doe_id,
        session_id=str(uuid4()),
        use_user_context=False,
    )

    memories_after_incognito_run = agent.get_user_memories(user_id=john_doe_id)
    print("Memories after the incognito run (unchanged):")
    pprint(memories_after_incognito_run)

    # Back to a normal run: the earlier memory is available again, and skydiving
    # was never recorded.
    agent.print_response(
        "What are my hobbies?",
        stream=True,
        user_id=john_doe_id,
        session_id=str(uuid4()),
    )
