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

DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"


def session_1():
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryCompiler(model=OpenAIChat(id="gpt-4o-mini"))
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        update_memory_on_run=True,
        markdown=True,
    )

    existing = agent.get_user_profile(USER_ID)
    if existing:
        print("Loaded from database:")
        print("  Profile:", existing.user_profile)
        print("  Knowledge items:", len(existing.memory_layers.get("knowledge", [])))

    agent.print_response(
        "We just launched our OAuth2 implementation in production! "
        "It's handling 10K requests per second with no issues.",
        user_id=USER_ID,
        stream=True,
    )


def session_2():
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryCompiler(model=OpenAIChat(id="gpt-4o-mini"))
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        memory_compiler=memory,
        markdown=True,
    )

    user = agent.get_user_profile(USER_ID)
    if user:
        print("\nPersisted across restart:")
        pprint(user.to_dict())

    agent.print_response(
        "What do you remember about my auth implementation and how it's performing?",
        user_id=USER_ID,
        stream=True,
    )


def cleanup():
    db = SqliteDb(db_file=DB_FILE)
    memory = MemoryCompiler()
    memory.db = db
    memory.delete_user_profile(USER_ID)


if __name__ == "__main__":
    session_1()
    session_2()
    # cleanup()
