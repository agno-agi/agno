"""
User-Namespaced Tools with Callable Tools
==========================================
This example demonstrates how to create per-user tool instances using
callable tools. Instead of passing a static list of tools to the agent,
you pass a function that creates the tools at runtime.

Why use callable tools?
-----------------------
- **Per-user isolation**: Each user gets their own database/resource
- **Dynamic configuration**: Tools can be configured based on user context
- **Resource management**: Create resources only when needed
- **Clean cleanup**: User resources are naturally scoped to their data

Key concepts:
- tools=callable: The function is called at runtime with run_context
- run_context.user_id: Available to create user-specific tool instances
- DuckDbTools: Each user gets their own DuckDB database file
- cache_callables=True: Reuse tool instances for the same user_id
  to avoid creating new database connections on every run

Example prompts to try:
- Run as user "alice": "Create a table called notes with columns id and text"
- Run as user "bob": "Show me all tables"
"""

import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools

# Create a temp directory for user databases
USER_DATA_DIR = Path(tempfile.mkdtemp(prefix="user_dbs_"))


# ============================================================================
# Tools Factory Function
# ============================================================================


def get_user_tools(run_context: RunContext):
    """Create user-specific tools at runtime.

    This function is called when agent.run() or agent.arun() is invoked.
    It receives the run_context which contains user_id, session_id, and
    other runtime information.

    With cache_callables=True, this function is only called once per
    user_id. Subsequent runs for the same user will reuse the cached tools,
    avoiding the creation of new database connections.

    Args:
        run_context: Runtime context with user_id, session_id, etc.

    Returns:
        List of tools configured for this specific user.
    """
    user_id = run_context.user_id or "anonymous"

    # Sanitize user_id for use in file names
    safe_user_id = user_id.replace("@", "_").replace(".", "_")

    # Create user-specific data directory
    user_dir = USER_DATA_DIR / safe_user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    # Each user gets their own DuckDB database
    db_path = str(user_dir / "user_data.db")

    # This message will only appear once per user when cache_callables=True
    print(f"[INIT] Creating DuckDB tools for user: {user_id}")
    print(f"[INIT] Database path: {db_path}")

    return [
        DuckDbTools(
            db_path=db_path,
            read_only=False,
        ),
    ]


# ============================================================================
# Create the Agent with Callable Tools
# ============================================================================
agent = Agent(
    name="Personal Database Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    # Pass the function, not a list of tools
    # The function will be called at runtime with run_context
    tools=get_user_tools,
    # Cache tool instances per user_id to reuse database connections
    cache_callables=True,
    instructions="""\
You are a personal database assistant. You help users manage their
personal DuckDB database.

When users ask questions:
1. Use the DuckDB tools to query or modify their database
2. Each user has their own isolated database
3. Help them create tables, insert data, and query their data
""",
    markdown=True,
)


# ============================================================================
# Main: Demonstrate User-Specific Tools
# ============================================================================
if __name__ == "__main__":
    print(f"User databases will be stored in: {USER_DATA_DIR}")

    # Alice creates a table
    print("\n" + "=" * 60)
    print("Alice creates a notes table:")
    print("=" * 60)
    agent.print_response(
        "Create a table called notes with columns: id (integer primary key), "
        "title (varchar), content (text). Then insert a note with title 'Hello' "
        "and content 'My first note'.",
        user_id="alice",
        stream=True,
    )

    # Bob creates a different table
    print("\n" + "=" * 60)
    print("Bob creates a tasks table:")
    print("=" * 60)
    agent.print_response(
        "Create a table called tasks with columns: id (integer primary key), "
        "task (varchar), done (boolean). Insert a task 'Learn Agno' with done=false.",
        user_id="bob",
        stream=True,
    )

    # Alice queries her data - should only see notes table
    print("\n" + "=" * 60)
    print("Alice queries her data (should only see notes):")
    print("=" * 60)
    agent.print_response(
        "Show me all tables and their contents",
        user_id="alice",
        stream=True,
    )

    # Bob queries his data - should only see tasks table
    print("\n" + "=" * 60)
    print("Bob queries his data (should only see tasks):")
    print("=" * 60)
    agent.print_response(
        "Show me all tables and their contents",
        user_id="bob",
        stream=True,
    )

    print(f"\nUser databases created in: {USER_DATA_DIR}")
