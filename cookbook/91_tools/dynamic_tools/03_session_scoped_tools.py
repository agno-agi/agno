"""
Session-Scoped Tools with Callable Tools
========================================
This example demonstrates how to create session-specific tool instances.
Unlike user-scoped tools, session-scoped tools create a new instance
for each conversation session.

Use cases:
- Temporary scratch databases for a single conversation
- Isolated workspaces that don't persist between sessions
- Testing environments that reset on each session

Key concepts:
- run_context.session_id: Unique identifier for the current session
- Ephemeral data: Data exists only for the duration of the session
- Clean slate: Each new session starts fresh
- cache_callables=False: Required! Cache key is user_id, not session_id
"""

import tempfile
from pathlib import Path
from typing import List, Union

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

# Create a temp directory for session databases
SESSION_DATA_DIR = Path(tempfile.mkdtemp(prefix="session_dbs_"))


# ============================================================================
# Tools Factory Function
# ============================================================================


def get_session_tools(run_context: RunContext) -> List[Union[Toolkit, Function]]:
    """Create session-specific tools at runtime.

    Each session gets its own DuckDB database, which is ephemeral
    and isolated from other sessions.

    Args:
        run_context: Runtime context with session_id

    Returns:
        List of tools configured for this specific session.
    """
    session_id = run_context.session_id

    # Create session-specific directory
    session_dir = SESSION_DATA_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Each session gets its own DuckDB database
    db_path = str(session_dir / "session_data.db")

    print("Creating session-scoped tools")
    print(f"Session ID: {session_id}")
    print(f"Database: {db_path}")

    return [
        DuckDbTools(db_path=db_path, read_only=False),
    ]


# ============================================================================
# Create the Agent with Callable Tools
# ============================================================================
agent = Agent(
    name="Session Workspace Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=get_session_tools,
    # IMPORTANT: Disable caching for session-scoped tools!
    # The cache key is based on user_id, not session_id, so caching
    # would cause different sessions to share the same tools.
    cache_callables=False,
    instructions="""\
You are a workspace assistant with a session-scoped database.

Key behaviors:
1. Each conversation session has its own isolated database
2. Data created in one session is not visible in another
3. Use DuckDB tools to create tables and store data
4. This is useful for temporary analysis or scratch work
""",
    markdown=True,
)


# ============================================================================
# Main: Demonstrate Session-Scoped Tools
# ============================================================================
if __name__ == "__main__":
    import uuid

    print(f"Session databases will be stored in: {SESSION_DATA_DIR}")

    # Session 1: Create some data
    session_1 = str(uuid.uuid4())
    print("\n" + "=" * 60)
    print(f"Session 1: {session_1[:8]}...")
    print("=" * 60)
    agent.print_response(
        "Create a table called scratch with columns: id (integer), data (varchar). "
        "Insert a row with id=1 and data='session 1 data'.",
        session_id=session_1,
        stream=True,
    )

    # Session 2: Different session, different database
    session_2 = str(uuid.uuid4())
    print("\n" + "=" * 60)
    print(f"Session 2: {session_2[:8]}... (different database)")
    print("=" * 60)
    agent.print_response(
        "Show me all tables in my database",
        session_id=session_2,
        stream=True,
    )

    # Back to Session 1: Data should still be there
    print("\n" + "=" * 60)
    print(f"Back to Session 1: {session_1[:8]}...")
    print("=" * 60)
    agent.print_response(
        "What data is in my scratch table?",
        session_id=session_1,
        stream=True,
    )

    print(f"\nSession databases created in: {SESSION_DATA_DIR}")
