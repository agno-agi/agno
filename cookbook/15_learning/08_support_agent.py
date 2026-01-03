"""
Customer Support Agent
===========================================
A support agent that remembers customers and learns resolution patterns.

Key Learning Patterns:
- User Profile: Customer history, preferences, past issues
- Session Context: Current ticket/issue being worked on
- Learned Knowledge: Resolution patterns that work

This agent gets better at support over time by:
1. Remembering each customer's history
2. Tracking what's been tried in current session
3. Learning patterns like "Error X is usually caused by Y"
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="support_learnings"),
)

# =============================================================================
# Support Agent Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Customer Support Agent for a SaaS product called "CloudSync".

## Your Approach

1. **Greet returning customers warmly** - You remember their history
2. **Check what's been tried** - Use session context to avoid repeating steps
3. **Search for known solutions** - Use search_learnings before troubleshooting
4. **Document resolutions** - Save learnings when you solve novel issues

## CloudSync Common Issues

- Sync errors: Usually permission or network related
- Performance: Often due to large file counts or slow connections
- Authentication: Token expiry, SSO configuration
- Billing: Plan limits, payment methods

## When to Save Learnings

Save when you discover:
- A non-obvious solution to a common error
- A pattern connecting symptoms to root causes
- A workaround for a known limitation

Don't save: Basic troubleshooting, one-off issues, customer-specific configs.
"""

# =============================================================================
# Create Support Agent
# =============================================================================
support_agent = Agent(
    name="CloudSync Support",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            instructions="Focus on: plan type, technical level, past issues, preferences",
        ),
        session_context=SessionContextConfig(
            enable_planning=False,  # Just summaries for support
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helpers
# =============================================================================
def show_customer_profile(user_id: str):
    """Show what we know about a customer."""
    profile = support_agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print(f"\n👤 Customer Profile ({user_id}):")
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    else:
        print(f"\n👤 New customer: {user_id}")
    print()


def show_ticket_context(session_id: str):
    """Show current ticket context."""
    context = support_agent.learning.stores["session_context"].get(session_id=session_id)
    if context and context.summary:
        print(f"\n🎫 Ticket Context:")
        print(f"   {context.summary}")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    # --- New Customer: First Contact ---
    print("=" * 60)
    print("Scenario 1: New Customer")
    print("=" * 60)

    customer_1 = "julia@startup.io"
    ticket_1 = "TICKET-001"

    show_customer_profile(customer_1)

    support_agent.print_response(
        "Hi, I'm having trouble with CloudSync. Files aren't syncing and I keep "
        "seeing 'Error 403: Access Denied' in the logs. I'm on the Pro plan.",
        user_id=customer_1,
        session_id=ticket_1,
        stream=True,
    )

    show_customer_profile(customer_1)

    # Continue the ticket
    print("\n--- Customer provides more info ---\n")
    support_agent.print_response(
        "I checked and the API key looks correct. We're using SSO with Okta.",
        user_id=customer_1,
        session_id=ticket_1,
        stream=True,
    )

    show_ticket_context(ticket_1)

    # --- Same Customer Returns ---
    print("\n" + "=" * 60)
    print("Scenario 2: Same Customer, New Issue")
    print("=" * 60)

    ticket_2 = "TICKET-002"

    support_agent.print_response(
        "Hey, it's me again. Different issue this time - sync is working but "
        "it's really slow. Taking 10+ minutes for small files.",
        user_id=customer_1,  # Same customer
        session_id=ticket_2,  # New ticket
        stream=True,
    )

    # --- Different Customer, Similar Issue ---
    print("\n" + "=" * 60)
    print("Scenario 3: Different Customer, Similar Issue")
    print("=" * 60)

    customer_2 = "kevin@enterprise.com"
    ticket_3 = "TICKET-003"

    support_agent.print_response(
        "We're getting 403 errors on our CloudSync integration. "
        "Started happening after we migrated to a new SSO provider.",
        user_id=customer_2,
        session_id=ticket_3,
        stream=True,
    )

    # --- Show learnings accumulated ---
    print("\n" + "=" * 60)
    print("Accumulated Support Learnings")
    print("=" * 60)
    results = support_agent.learning.stores["learned_knowledge"].search(
        query="403 error SSO authentication",
        limit=5,
    )
    if results:
        print("\n📚 Relevant learnings:")
        for r in results:
            print(f"   > {getattr(r, 'title', 'Untitled')}")
    else:
        print("\n📚 No learnings accumulated yet")
