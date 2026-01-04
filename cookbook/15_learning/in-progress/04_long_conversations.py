"""
Session Context: Long Conversations
===================================
Handling context window limitations.

LLMs have limited context windows. When conversations get long:
- Early messages get truncated
- Important context can be lost
- The agent may forget what was discussed

Session Context solves this by:
1. Maintaining a running summary
2. Tracking goals and progress separately
3. Providing this context even when messages are truncated

This cookbook demonstrates handling very long conversations.

Run:
    python cookbook/15_learning/session_context/04_long_conversations.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Aggressive Truncation
# ============================================================================
# Simulate limited context by keeping only last 2 messages
agent = Agent(
    name="Long Conversation Agent",
    model=model,
    db=db,
    instructions="""\
You are helping with a complex, multi-step project.

Use the session context to stay aware of:
- What we're trying to accomplish (goal)
- The overall plan
- What has been completed (progress)
- Key decisions and constraints

Even if you can't see early messages, refer to the session context
to maintain continuity.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
    ),
    # Aggressive truncation: keep only 2 recent exchanges
    num_history_runs=2,
    markdown=True,
)


# ============================================================================
# Demo: Long Conversation
# ============================================================================
def demo_long_conversation():
    """Simulate a long conversation with many turns."""
    print("=" * 60)
    print("Demo: Long Conversation (Simulated Truncation)")
    print("=" * 60)
    print("\n⚠️  Agent only sees last 2 message exchanges in context")
    print("    Session context provides continuity\n")

    user = "long_demo@example.com"
    session = "long_session_001"

    # Turn 1: Set the scene
    print("\n--- Turn 1: Project setup ---\n")
    agent.print_response(
        "I need help building a complete e-commerce backend. "
        "Requirements: user auth, product catalog, cart, checkout, "
        "order management, and payment integration with Stripe.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 2: First component
    print("\n--- Turn 2: Auth discussion ---\n")
    agent.print_response(
        "Let's start with auth. I want to use JWT tokens with refresh token rotation.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 3: Decision
    print("\n--- Turn 3: Auth complete ---\n")
    agent.print_response(
        "Auth is done! I implemented JWT with 15min access tokens "
        "and 7-day refresh tokens. What's next?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 4: Next component
    print("\n--- Turn 4: Product catalog ---\n")
    agent.print_response(
        "For the product catalog, I need categories, products, "
        "variants (size, color), and inventory tracking.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 5: Implementation
    print("\n--- Turn 5: Catalog progress ---\n")
    agent.print_response(
        "I've set up the product models with variants. "
        "Inventory is tracked per-variant.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 6: More progress
    print("\n--- Turn 6: Cart system ---\n")
    agent.print_response(
        "Now working on the cart. Guest carts vs user carts - "
        "how should I handle cart merging on login?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 7: Even more
    print("\n--- Turn 7: Cart complete ---\n")
    agent.print_response(
        "Cart is done with merge-on-login! Moving to checkout.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 8: Test recall - early messages are truncated
    print("\n" + "-" * 40)
    print("At this point, Turn 1-5 are truncated from context")
    print("Session context should still know about them")
    print("-" * 40)

    print("\n--- Turn 8: Test recall ---\n")
    agent.print_response(
        "Wait, remind me - what token expiry times did we decide on "
        "for the auth system we built at the start?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Turn 9: Overall progress
    print("\n--- Turn 9: Overall status ---\n")
    agent.print_response(
        "Give me a summary of everything we've built so far and what's left to do.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Context Recovery
# ============================================================================
def demo_context_recovery():
    """Show how session context helps recover from truncation."""
    print("\n" + "=" * 60)
    print("Demo: Context Recovery")
    print("=" * 60)

    user = "recovery_demo@example.com"
    session = "recovery_session"

    # Establish important constraints
    print("\n--- Establish constraints ---\n")
    agent.print_response(
        "I'm building a real-time trading system. Critical constraints: "
        "1) Max 10ms latency for order execution "
        "2) Must handle 100k orders/second "
        "3) Zero data loss - all orders must persist "
        "4) Audit trail required for compliance",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Several turns later
    for i in range(5):
        print(f"\n--- Turn {i + 2}: Technical discussion ---\n")
        agent.print_response(
            f"Technical question #{i + 1}: What about using Redis for order queueing?",
            user_id=user,
            session_id=session,
            stream=True,
        )

    # Test if constraints are remembered
    print("\n--- Test constraint recall ---\n")
    agent.print_response(
        "Before we proceed, remind me of all the critical constraints "
        "we established at the beginning.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_long_conversation()
    demo_context_recovery()

    print("\n" + "=" * 60)
    print("✅ Session context handles long conversations")
    print("   Even with aggressive truncation, context persists")
    print("   Goals, plans, and key decisions are preserved")
    print("=" * 60)
