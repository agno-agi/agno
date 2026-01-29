"""
Combined Dynamic Knowledge and Tools
====================================
This example demonstrates using both callable knowledge and callable tools
together for complete per-user isolation of both data storage and
semantic search capabilities.

Use case: A personal assistant where each user has:
- Their own vector database for RAG (knowledge)
- Their own DuckDB for structured data (tools)

Key concepts:
- knowledge=callable: Per-user vector database
- tools=callable: Per-user DuckDB
- Complete data isolation at both layers
"""

import tempfile
from pathlib import Path
from typing import List, Union

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.vectordb.chroma import ChromaDb

# Create temp directories for user data
USER_DATA_ROOT = Path(tempfile.mkdtemp(prefix="user_data_"))


# ============================================================================
# Knowledge Factory - Per-User Vector DB
# ============================================================================


def get_user_knowledge(run_context: RunContext) -> Knowledge:
    """Create user-specific knowledge base at runtime.

    Each user gets their own ChromaDB collection for semantic search.

    Args:
        run_context: Runtime context with user_id

    Returns:
        Knowledge instance configured for this user.
    """
    user_id = run_context.user_id or "anonymous"
    safe_user_id = user_id.replace("@", "_").replace(".", "_")

    print(f"Creating knowledge base for user: {user_id}")

    user_dir = USER_DATA_ROOT / safe_user_id / "knowledge"
    user_dir.mkdir(parents=True, exist_ok=True)

    return Knowledge(
        name=f"Knowledge for {user_id}",
        vector_db=ChromaDb(
            name=f"user_{safe_user_id}_knowledge",
            collection=f"user_{safe_user_id}_docs",
            path=str(user_dir),
            persistent_client=True,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        max_results=5,
    )


# ============================================================================
# Tools Factory - Per-User DuckDB
# ============================================================================


def get_user_tools(run_context: RunContext) -> List[Union[Toolkit, Function]]:
    """Create user-specific tools at runtime.

    Each user gets their own DuckDB database for structured data.

    Args:
        run_context: Runtime context with user_id

    Returns:
        List of tools configured for this user.
    """
    user_id = run_context.user_id or "anonymous"
    safe_user_id = user_id.replace("@", "_").replace(".", "_")

    print(f"Creating DuckDB tools for user: {user_id}")

    user_dir = USER_DATA_ROOT / safe_user_id / "data"
    user_dir.mkdir(parents=True, exist_ok=True)

    db_path = str(user_dir / "user_data.db")
    print(f"Database path: {db_path}")

    return [
        DuckDbTools(db_path=db_path, read_only=False),
    ]


# ============================================================================
# Create Agent with Both Callable Knowledge and Tools
# ============================================================================
agent = Agent(
    name="Personal Data Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    # Both are callables - resolved at runtime per-user
    knowledge=get_user_knowledge,
    tools=get_user_tools,
    search_knowledge=True,
    instructions="""\
You are a personal data assistant with two storage systems:

1. **Knowledge Base** (Vector DB) - For semantic search
   - Use search_knowledge_base to find relevant documents
   - Great for unstructured text and semantic queries

2. **Database** (DuckDB) - For structured data
   - Use DuckDB tools to create tables and run SQL queries
   - Great for structured records, lists, and analytics

Each user has their own isolated knowledge base AND database.
Choose the right storage based on the data type:
- Structured data (lists, records, numbers) -> DuckDB
- Unstructured text (notes, articles, docs) -> Knowledge Base
""",
    markdown=True,
)


# ============================================================================
# Helper to Load Content for a User
# ============================================================================


def load_knowledge_for_user(user_id: str, content: str, name: str):
    """Load content into a user's knowledge base."""
    run_context = RunContext(
        run_id="load",
        session_id="load",
        user_id=user_id,
    )
    knowledge = get_user_knowledge(run_context)
    print(f"Loading '{name}' into knowledge base for {user_id}...")
    knowledge.insert(name=name, text_content=content)
    print("Loaded successfully")


# ============================================================================
# Main: Demonstrate Combined Dynamic Resources
# ============================================================================
if __name__ == "__main__":
    print(f"User data root: {USER_DATA_ROOT}")

    # Load different knowledge for different users
    load_knowledge_for_user(
        user_id="alice",
        content="Alice's company policy: All code must be reviewed before merging. "
        "Use feature branches and require at least 2 approvals.",
        name="Company Policy",
    )

    load_knowledge_for_user(
        user_id="bob",
        content="Bob's project notes: The API uses REST with JSON. "
        "Authentication is via JWT tokens. Rate limit is 100 req/min.",
        name="Project Notes",
    )

    # Alice uses both knowledge and tools
    print("\n" + "=" * 60)
    print("Alice: Using knowledge base")
    print("=" * 60)
    agent.print_response(
        "What's our code review policy?",
        user_id="alice",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Alice: Using DuckDB")
    print("=" * 60)
    agent.print_response(
        "Create a table called tasks with id, title, and status columns. "
        "Add a task: 'Review PR #123' with status 'pending'.",
        user_id="alice",
        stream=True,
    )

    # Bob uses both - but sees different data
    print("\n" + "=" * 60)
    print("Bob: Using knowledge base (different content)")
    print("=" * 60)
    agent.print_response(
        "What's the API rate limit?",
        user_id="bob",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Bob: Checking Alice's data (should be empty for Bob)")
    print("=" * 60)
    agent.print_response(
        "Show me all tables in my database",
        user_id="bob",
        stream=True,
    )

    # Show directory structure
    print("\n" + "=" * 60)
    print("Data directory structure:")
    print("=" * 60)
    for user_dir in USER_DATA_ROOT.iterdir():
        print(f"  {user_dir.name}/")
        for subdir in user_dir.iterdir():
            print(f"    {subdir.name}/")
            for file in subdir.iterdir():
                print(f"      {file.name}")
