"""
Combined: User Profile + Entity Memory
======================================
Personal memory + external knowledge.

This combination is ideal for:
- CRM-style applications
- Sales and account management
- Research assistants
- Consultant tools

User Profile tracks: Who the user is
Entity Memory tracks: What they're researching/managing

Run:
    python cookbook/15_learning/combined/02_user_plus_entities.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    EntityMemoryConfig,
    LearningMachine,
    LearningMode,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with User Profile + Entity Memory
# ============================================================================
agent = Agent(
    name="Account Manager Assistant",
    model=model,
    db=db,
    instructions="""\
You are an account manager assistant that helps track:
1. User information (who you're talking to)
2. Account/company information (external entities)

Use user profile to remember the person you're helping.
Use entity memory to track companies, contacts, and deals.

When users mention accounts, prospects, or companies:
- Create entities for them
- Track facts, events, and relationships
- Help retrieve this information later
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="sales",  # Team namespace
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Sales Rep Managing Accounts
# ============================================================================
def demo_sales_rep():
    """Show a sales rep managing accounts."""
    print("=" * 60)
    print("Demo: Sales Rep Managing Accounts")
    print("=" * 60)

    user = "sarah_sales@company.com"
    session = "sales_session"

    # Establish user
    print("\n--- Sales rep introduces themselves ---\n")
    agent.print_response(
        "Hi, I'm Sarah from the enterprise sales team. "
        "I manage accounts in the financial services sector.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Add account info
    print("\n--- Log account information ---\n")
    agent.print_response(
        "Just had a call with BigBank Corp. Key details: "
        "- Main contact: John Chen, VP of Technology "
        "- Budget: $500K annually "
        "- Pain points: Legacy systems, slow deployment cycles "
        "- Timeline: Looking to decide by Q2 "
        "- They use Java and Oracle currently "
        "Please track all of this.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query later
    print("\n--- Query account ---\n")
    agent.print_response(
        "What do we know about BigBank Corp?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Research Assistant
# ============================================================================
def demo_research_assistant():
    """Show a research assistant tracking companies."""
    print("\n" + "=" * 60)
    print("Demo: Research Assistant")
    print("=" * 60)

    user = "researcher@company.com"
    session = "research_session"

    # Establish user
    print("\n--- Researcher intro ---\n")
    agent.print_response(
        "I'm a market researcher focusing on AI startups. "
        "I prefer data-driven analysis with numbers and trends.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Research multiple companies
    print("\n--- Track multiple companies ---\n")
    agent.print_response(
        "Track these AI companies I'm researching: "
        "1. AIStart - Series A, $20M raised, 30 employees, focus on NLP "
        "2. MLOps Inc - Series B, $50M raised, 100 employees, MLOps platform "
        "3. DataBrain - Seed, $5M raised, 10 employees, automated data science",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Analysis query
    print("\n--- Analysis query ---\n")
    agent.print_response(
        "Compare the AI companies I'm tracking. "
        "Which is at the most interesting stage?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Building Relationships
# ============================================================================
def demo_relationships():
    """Show tracking relationships between entities."""
    print("\n" + "=" * 60)
    print("Demo: Building Entity Relationships")
    print("=" * 60)

    user = "analyst@company.com"
    session = "relationship_session"

    # Add entities with relationships
    print("\n--- Track company ecosystem ---\n")
    agent.print_response(
        "Track this information about the TechCorp ecosystem: "
        "- TechCorp is a Fortune 500 company, CEO is Maria Johnson "
        "- TechCorp acquired DataSmart last year "
        "- TechCorp has a partnership with CloudGiant "
        "- Bob Smith is CTO of TechCorp, previously at Google "
        "- DataSmart's founder, Alex Lee, now reports to Bob",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query relationships
    print("\n--- Query relationships ---\n")
    agent.print_response(
        "What's the connection between TechCorp and DataSmart? "
        "Who are the key people involved?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: User + Entity Interaction
# ============================================================================
def demo_combined_interaction():
    """Show how user profile and entity memory work together."""
    print("\n" + "=" * 60)
    print("Demo: Combined User + Entity Interaction")
    print("=" * 60)

    user = "premium_user@company.com"
    session = "premium_session"

    # Establish user context
    print("\n--- Establish user context ---\n")
    agent.print_response(
        "I'm the VP of Sales at TechCorp. I manage all enterprise accounts. "
        "I need detailed reports with action items.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Add account with user's perspective
    print("\n--- Add account from user's perspective ---\n")
    agent.print_response(
        "Log my meeting with MegaCorp: "
        "- They're our largest prospect, $2M deal "
        "- Met with their CIO, Jennifer Smith "
        "- They're concerned about our support SLAs "
        "- I promised to follow up with a custom proposal "
        "- Next meeting scheduled for March 15",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query with user context
    print("\n--- Request formatted for user's role ---\n")
    agent.print_response(
        "Give me an executive summary of the MegaCorp opportunity "
        "with recommended next steps.",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )

    print("\n💡 Notice: Summary should be formatted for a VP")
    print("   (executive level, with action items)")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_sales_rep()
    demo_research_assistant()
    demo_relationships()
    demo_combined_interaction()

    print("\n" + "=" * 60)
    print("✅ User Profile + Entity Memory")
    print("   User Profile = who you're talking to")
    print("   Entity Memory = what they're tracking")
    print("=" * 60)
