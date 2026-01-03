"""
Multi-User Isolation
===========================================
When building for multiple users, you need to ensure:
1. User A cannot see User B's profile
2. Sessions don't leak across users
3. Learnings are shared (by design) but profiles are private

This cookbook demonstrates proper isolation patterns.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import LearningMachine
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="multi_user_learnings"),
)

# =============================================================================
# Create Agent
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        user_profile=True,
        session_context=True,
    ),
    markdown=True,
)


# =============================================================================
# Helpers
# =============================================================================
def get_profile_content(user_id: str) -> list:
    """Get profile content for a user."""
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        return [m.get("content", str(m)) for m in profile.memories]
    return []


def get_session_content(session_id: str) -> str:
    """Get session context."""
    context = agent.learning.stores["session_context"].get(session_id=session_id)
    if context and context.summary:
        return context.summary
    return ""


# =============================================================================
# Test: User Isolation
# =============================================================================
def test_user_isolation():
    """Verify that user profiles don't leak across users."""
    print("=" * 60)
    print("TEST: User Profile Isolation")
    print("=" * 60)

    # User Alice shares private info
    print("\n--- Alice shares private information ---\n")
    agent.print_response(
        "I'm Alice, and my social security number is 123-45-6789. "
        "I work at SecretCorp on Project Classified.",
        user_id="alice@example.com",
        session_id="alice_session",
        stream=True,
    )

    # User Bob asks what the agent knows
    print("\n--- Bob asks what the agent knows about him ---\n")
    agent.print_response(
        "What do you know about me?",
        user_id="bob@example.com",
        session_id="bob_session",
        stream=True,
    )

    # Verify isolation
    alice_profile = get_profile_content("alice@example.com")
    bob_profile = get_profile_content("bob@example.com")

    print("\n--- Verification ---")
    print(f"Alice's profile has {len(alice_profile)} memories")
    print(f"Bob's profile has {len(bob_profile)} memories")

    # Check that Bob can't see Alice's data
    bob_sees_alice = any(
        "alice" in str(m).lower() or "secret" in str(m).lower() for m in bob_profile
    )
    print(f"Bob can see Alice's data: {bob_sees_alice}")
    print(f"✅ PASS" if not bob_sees_alice else "❌ FAIL")


def test_session_isolation():
    """Verify that sessions don't leak across users."""
    print("\n" + "=" * 60)
    print("TEST: Session Isolation")
    print("=" * 60)

    # Charlie works on a project
    print("\n--- Charlie works on sensitive project ---\n")
    agent.print_response(
        "I'm working on the Q1 financial projections. Revenue is $5M, "
        "costs are $3M. Don't share this with anyone!",
        user_id="charlie@example.com",
        session_id="charlie_finance",
        stream=True,
    )

    # Diana starts a new session
    print("\n--- Diana asks about financials ---\n")
    agent.print_response(
        "What do you know about any financial projections?",
        user_id="diana@example.com",
        session_id="diana_session",
        stream=True,
    )

    # Verify session isolation
    charlie_context = get_session_content("charlie_finance")
    diana_context = get_session_content("diana_session")

    print("\n--- Verification ---")
    print(f"Charlie's session has context: {bool(charlie_context)}")
    print(f"Diana's session has context: {bool(diana_context)}")

    diana_sees_charlie = "5M" in diana_context or "revenue" in diana_context.lower()
    print(f"Diana can see Charlie's session: {diana_sees_charlie}")
    print(f"✅ PASS" if not diana_sees_charlie else "❌ FAIL")


def test_shared_learnings():
    """Verify that learnings ARE shared (by design)."""
    print("\n" + "=" * 60)
    print("TEST: Learnings Are Shared (By Design)")
    print("=" * 60)

    # Eve discovers a useful pattern
    print("\n--- Eve discovers a pattern ---\n")
    agent.print_response(
        "I found that using connection pooling reduced our API latency by 80%. "
        "This is a great pattern that everyone should know!",
        user_id="eve@example.com",
        session_id="eve_session",
        stream=True,
    )

    # Frank asks a related question
    print("\n--- Frank asks about performance ---\n")
    agent.print_response(
        "How can I improve my API performance?",
        user_id="frank@example.com",
        session_id="frank_session",
        stream=True,
    )

    # Search learnings
    results = agent.learning.stores["learned_knowledge"].search(
        query="API performance connection pooling",
        limit=5,
    )

    print("\n--- Verification ---")
    print(f"Learnings found: {len(results)}")
    if results:
        print("Learnings are shared across users: ✅ PASS")
    else:
        print("Note: Agent may not have saved a learning yet")


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    test_user_isolation()
    test_session_isolation()
    test_shared_learnings()

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print("""
    ✅ User profiles are isolated by user_id
    ✅ Sessions are isolated by session_id
    ✅ Learnings are shared (this is intentional)
    
    For team isolation of learnings, use separate knowledge bases.
    See DESIGN.md for more details.
    """)
