"""
User-Namespaced Knowledge with Callable Knowledge
==================================================
This example demonstrates how to create per-user knowledge bases using
callable knowledge. Instead of passing a static Knowledge instance to the
agent, you pass a function that creates the knowledge base at runtime.

Why use callable knowledge?
---------------------------
- **Per-user isolation**: Each user gets their own namespace in the vector DB
- **Simplified access control**: No need for metadata filtering across shared indexes
- **Efficient auditing**: User data is partition-scoped, not scattered across indexes
- **Clean deletion**: Removing a user's data is a simple partition drop

Key concepts:
- knowledge=callable: The function is called at runtime with run_context
- run_context.user_id: Available to create user-specific namespaces
- ChromaDb collections: Each user gets their own collection

Example prompts to try:
- Run as user "alice": "What documents do I have?"
- Run as user "bob": "Search my knowledge base"
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.vectordb.chroma import ChromaDb

# ============================================================================
# Knowledge Factory Function
# ============================================================================


def get_user_knowledge(run_context: RunContext) -> Knowledge:
    """Create a user-specific knowledge base at runtime.

    This function is called when agent.run() or agent.arun() is invoked.
    It receives the run_context which contains user_id, session_id, and
    other runtime information.

    Args:
        run_context: Runtime context with user_id, session_id, etc.

    Returns:
        Knowledge instance configured for this specific user.
    """
    user_id = run_context.user_id or "anonymous"

    # Sanitize user_id for use in collection/path names
    safe_user_id = user_id.replace("@", "_").replace(".", "_")

    print(f"Creating knowledge base for user: {user_id}")

    # Each user gets their own ChromaDb collection
    # This provides complete isolation at the vector DB level
    return Knowledge(
        name=f"Knowledge for {user_id}",
        vector_db=ChromaDb(
            name=f"user_{safe_user_id}_docs",
            collection=f"user_{safe_user_id}_collection",
            path=f"tmp/chromadb/users/{safe_user_id}",
            persistent_client=True,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        max_results=5,
    )


# ============================================================================
# Create the Agent with Callable Knowledge
# ============================================================================
agent = Agent(
    name="Personal Knowledge Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    # Pass the function, not a Knowledge instance
    # The function will be called at runtime with run_context
    knowledge=get_user_knowledge,
    search_knowledge=True,
    instructions="""\
You are a personal knowledge assistant. You help users search and manage
their personal knowledge base.

When users ask questions:
1. Search their knowledge base first
2. If no relevant documents found, let them know
3. Suggest they can add documents to their knowledge base
""",
    markdown=True,
)


# ============================================================================
# Helper to Load User-Specific Content
# ============================================================================


def load_user_content(user_id: str, content_url: str, content_name: str):
    """Load content into a user's knowledge base.

    Since knowledge is created dynamically, we need to create the
    knowledge instance manually when loading content outside of a run.
    """
    # Create a minimal run_context for the knowledge factory
    run_context = RunContext(
        run_id="load",
        session_id="load",
        user_id=user_id,
    )

    # Get the user's knowledge instance
    knowledge = get_user_knowledge(run_context)

    # Load the content
    print(f"Loading '{content_name}' for user {user_id}...")
    knowledge.insert(name=content_name, url=content_url)
    print("Content loaded successfully")


# ============================================================================
# Main: Demonstrate User-Specific Knowledge
# ============================================================================
if __name__ == "__main__":
    # Load different content for different users
    load_user_content(
        user_id="alice",
        content_url="https://docs.agno.com/introduction.md",
        content_name="Agno Introduction",
    )

    load_user_content(
        user_id="bob",
        content_url="https://docs.agno.com/agents/introduction.md",
        content_name="Agno Agents Guide",
    )

    # Query as Alice - she only sees her documents
    print("\n" + "=" * 60)
    print("Querying as Alice:")
    print("=" * 60)
    agent.print_response(
        "What is Agno?",
        user_id="alice",
        stream=True,
    )

    # Query as Bob - he only sees his documents
    print("\n" + "=" * 60)
    print("Querying as Bob:")
    print("=" * 60)
    agent.print_response(
        "Tell me about agents",
        user_id="bob",
        stream=True,
    )

    # Query as anonymous user - separate namespace
    print("\n" + "=" * 60)
    print("Querying as anonymous (no user_id):")
    print("=" * 60)
    agent.print_response(
        "What documents do I have?",
        stream=True,
    )
