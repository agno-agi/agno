"""Memory Persistence - Memory survives app restarts.

This continues Sarah's story, demonstrating that memory persists in the database.
Simulates two separate app sessions - the agent still knows Sarah.

Run after 03_agentic_memory.py to see accumulated memory persist.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# Same database as all previous cookbooks
DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"


def session_1():
    """First session - show existing memory and add more."""
    print("=" * 60)
    print("SESSION 1: Continuing Sarah's story")
    print("=" * 60)

    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryCompiler(model=OpenAIChat(id="gpt-4o-mini"))
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    # Show accumulated memory from previous cookbooks
    existing = agent.get_user_profile(USER_ID)
    if existing:
        print("\nLoaded from database (accumulated from 01, 02, 03):")
        print("  Profile:", existing.user_profile)
        print("  Knowledge items:", len(existing.memory_layers.get("knowledge", [])))
    else:
        print("\n(Run previous cookbooks first for full experience)")

    # Add new information
    print("\nSarah shares new info in this session:")
    agent.print_response(
        "We just launched our OAuth2 implementation in production! "
        "It's handling 10K requests per second with no issues.",
        user_id=USER_ID,
        stream=True,
    )

    print("\nMemory saved to database.")


def session_2():
    """Second session - completely fresh instances, memory persists."""
    print("\n" + "=" * 60)
    print("SESSION 2: Fresh app instance (simulating restart)")
    print("=" * 60)

    # Create completely fresh instances
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryCompiler(model=OpenAIChat(id="gpt-4o-mini"))
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        markdown=True,
    )

    # Show that memory persisted
    user = agent.get_user_profile(USER_ID)
    if user:
        print("\nLoaded from database (persisted across restart):")
        pprint(user.to_dict())

    # Agent uses remembered context
    print("\nAsking a question - agent should use persisted context:")
    agent.print_response(
        "What do you remember about my auth implementation and how it's performing?",
        user_id=USER_ID,
        stream=True,
    )


def cleanup():
    """Optional: clean up for fresh demo runs."""
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryCompiler()
    memory.db = db
    memory.delete_user_profile(USER_ID)
    print("\nCleaned up Sarah's memory for fresh demo runs.")


if __name__ == "__main__":
    session_1()

    print("\n" + "-" * 60)
    print("[Simulating app restart - all objects destroyed and recreated]")
    print("-" * 60)

    session_2()

    print("\n" + "=" * 60)
    print("PERSISTENCE DEMO COMPLETE")
    print("=" * 60)
    print("""
The agent remembered Sarah across a simulated app restart because:
1. Memory is stored in SQLite database (tmp/user_memory.db)
2. User profile is loaded by user_id on each session
3. All accumulated context from cookbooks 01-05 persists

To start fresh, uncomment the cleanup() call below.
""")

    # Uncomment to reset for fresh demo:
    # cleanup()
