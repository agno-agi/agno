"""Memory Persistence - Memory survives across sessions.

This example shows that memory persists in the database,
so the agent remembers users across app restarts.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryManagerV2
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

DB_FILE = "tmp/persistent_memory.db"
USER_ID = "persistent-user"


def session_1():
    """First session - user shares information."""
    print("SESSION 1: User shares information")

    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryManagerV2(db=db)
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        memory_manager_v2=memory,
        markdown=True,
    )

    agent.print_response(
        "I'm Casey, a DevOps engineer. I work with Kubernetes and Terraform.",
        user_id=USER_ID,
        stream=True,
    )
    print("\nMemory saved to database.")


def session_2():
    """Second session - agent remembers the user."""
    print("\nSESSION 2: New session (simulating app restart)")

    # Create fresh instances
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryManagerV2(db=db)
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        memory_manager_v2=memory,
        markdown=True,
    )

    # Show what was loaded from database
    profile = memory.get_user_profile(USER_ID)
    if profile:
        print("Loaded from database:")
        pprint(profile.to_dict())

    # Agent uses remembered context
    agent.print_response(
        "What's the best way to manage secrets?",
        user_id=USER_ID,
        stream=True,
    )


def cleanup():
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryManagerV2(db=db)
    memory.delete_user_profile(USER_ID)
    print("\nCleaned up.")


if __name__ == "__main__":
    session_1()
    print("\n[Simulating app restart...]\n")
    session_2()
    cleanup()
