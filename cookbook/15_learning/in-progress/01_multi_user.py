"""
Advanced: Multi-User Learning
=============================
How learning works across multiple users.

Key concepts:
- User profiles are always per-user (user_id scoped)
- Session contexts are per-session (session_id scoped)
- Entity memory and learned knowledge use namespace scoping

This cookbook demonstrates:
1. Private data (user-scoped)
2. Shared data (global namespace)
3. Team data (custom namespace)

Run:
    python cookbook/15_learning/advanced/01_multi_user.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="multi_user_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# ============================================================================
# Agent with Multiple Scoping Levels
# ============================================================================
agent = Agent(
    name="Multi-User Agent",
    model=model,
    db=db,
    instructions="""\
You help users while respecting data boundaries.

Data scoping:
- User profile: PRIVATE to each user (automatic)
- Entity memory: SHARED based on namespace configuration
- Learned knowledge: SHARED based on namespace configuration

When users share personal info, it goes to their profile.
When users share generally useful insights, save as learnings.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            # Always scoped to user_id (no configuration needed)
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",  # Shared across all users
            enable_agent_tools=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",  # Shared across all users
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: User Isolation
# ============================================================================
def demo_user_isolation():
    """Show that user profiles are isolated."""
    print("=" * 60)
    print("Demo: User Profile Isolation")
    print("=" * 60)

    # Alice shares personal info
    print("\n--- Alice shares personal info ---\n")
    agent.print_response(
        "I'm Alice, I'm a morning person and I love coffee.",
        user_id="alice@company.com",
        session_id="alice_session",
        stream=True,
    )

    # Bob shares personal info
    print("\n--- Bob shares personal info ---\n")
    agent.print_response(
        "I'm Bob, I'm a night owl and I prefer tea.",
        user_id="bob@company.com",
        session_id="bob_session",
        stream=True,
    )

    # Alice asks about herself
    print("\n--- Alice queries her profile ---\n")
    agent.print_response(
        "What do you know about me?",
        user_id="alice@company.com",
        session_id="alice_query",
        stream=True,
    )

    # Bob asks about himself
    print("\n--- Bob queries his profile ---\n")
    agent.print_response(
        "What do you know about me?",
        user_id="bob@company.com",
        session_id="bob_query",
        stream=True,
    )

    print("\n💡 Each user only sees their own profile data")


# ============================================================================
# Demo: Shared Learnings
# ============================================================================
def demo_shared_learnings():
    """Show that learnings are shared across users."""
    print("\n" + "=" * 60)
    print("Demo: Shared Learnings (Global Namespace)")
    print("=" * 60)

    # Alice discovers something
    print("\n--- Alice saves a learning ---\n")
    agent.print_response(
        "I discovered that for Python, using `uv` instead of `pip` is much faster. "
        "Please save this as a learning for everyone.",
        user_id="alice@company.com",
        session_id="alice_learn",
        stream=True,
    )

    # Bob benefits from Alice's learning
    print("\n--- Bob searches for Python tips ---\n")
    agent.print_response(
        "What are some tips for faster Python package installation?",
        user_id="bob@company.com",
        session_id="bob_search",
        stream=True,
    )

    print("\n💡 Bob found Alice's learning - global namespace shares across users")


# ============================================================================
# Demo: Shared Entities
# ============================================================================
def demo_shared_entities():
    """Show that entities are shared in global namespace."""
    print("\n" + "=" * 60)
    print("Demo: Shared Entities (Global Namespace)")
    print("=" * 60)

    # Alice adds customer info
    print("\n--- Alice logs customer info ---\n")
    agent.print_response(
        "Track this: Acme Corp is a customer, they use PostgreSQL, "
        "their CTO is Jane Smith.",
        user_id="alice@company.com",
        session_id="alice_entity",
        stream=True,
    )

    # Bob queries customer info
    print("\n--- Bob queries customer ---\n")
    agent.print_response(
        "What do we know about Acme Corp?",
        user_id="bob@company.com",
        session_id="bob_entity",
        stream=True,
    )

    print("\n💡 Bob can see the entity Alice created - shared namespace")


# ============================================================================
# Summary
# ============================================================================
def summary():
    """Print summary of multi-user behavior."""
    print("\n" + "=" * 60)
    print("Summary: Multi-User Data Scoping")
    print("=" * 60)
    print("""
┌─────────────────────────────────────────────────────────────┐
│ Learning Type      │ Scope              │ Controlled By     │
├─────────────────────────────────────────────────────────────┤
│ User Profile       │ Always per-user    │ user_id (auto)    │
│ Session Context    │ Always per-session │ session_id (auto) │
│ Entity Memory      │ Configurable       │ namespace param   │
│ Learned Knowledge  │ Configurable       │ namespace param   │
└─────────────────────────────────────────────────────────────┘

Namespace options:
- "global"  → All users share
- "user"    → Per-user isolation (requires user_id)
- "custom"  → Team/project isolation (e.g., "sales", "eng")
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_user_isolation()
    demo_shared_learnings()
    demo_shared_entities()
    summary()
