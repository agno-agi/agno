"""
Entity Memory: Namespace Sharing
================================
Controlling who can see entity data.

Namespace determines the sharing boundary:

- "global" (default): Shared with everyone
  - Good for: Company-wide knowledge base
  - Example: Info about customers, partners, competitors

- "user": Private per user
  - Good for: Personal contacts, private notes
  - Example: User's personal network

- Custom string: Team or project isolation
  - Good for: Department-specific data
  - Example: "sales", "engineering", "project_x"

When namespace="user", the user_id is required at runtime.

Run:
    python cookbook/15_learning/entity_memory/03_namespace_sharing.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, EntityMemoryConfig, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Agent with Global Namespace (Default)
# ============================================================================
global_agent = Agent(
    name="Global Entity Agent",
    model=model,
    db=db,
    instructions="You track information about companies and people. Data is shared globally.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",  # Default: shared with everyone
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Agent with User Namespace (Private)
# ============================================================================
private_agent = Agent(
    name="Private Entity Agent",
    model=model,
    db=db,
    instructions="You track personal contacts and private notes. Data is private per user.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="user",  # Private per user
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Agents with Team Namespaces
# ============================================================================
sales_agent = Agent(
    name="Sales Entity Agent",
    model=model,
    db=db,
    instructions="You track sales prospects and customer information for the sales team.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="sales",  # Sales team only
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

engineering_agent = Agent(
    name="Engineering Entity Agent",
    model=model,
    db=db,
    instructions="You track technical systems, services, and infrastructure for engineering.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="engineering",  # Engineering team only
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Global Sharing
# ============================================================================
def demo_global_sharing():
    """Show global namespace - visible to everyone."""
    print("=" * 60)
    print("Demo: Global Namespace")
    print("=" * 60)

    session = "global_session"

    # User A adds entity
    print("\n--- User A adds competitor info ---\n")
    global_agent.print_response(
        "Add this competitor info: BigRival Inc is our main competitor. "
        "They raised $200M and have 500 employees.",
        user_id="user_a@company.com",
        session_id=session + "_a",
        stream=True,
    )

    # User B can see it
    print("\n--- User B queries the same entity ---\n")
    global_agent.print_response(
        "What do we know about BigRival Inc?",
        user_id="user_b@company.com",
        session_id=session + "_b",
        stream=True,
    )

    print("\n💡 Global namespace: Data is shared across all users")


# ============================================================================
# Demo: User-Private Namespace
# ============================================================================
def demo_private_namespace():
    """Show user namespace - private to each user."""
    print("\n" + "=" * 60)
    print("Demo: User Namespace (Private)")
    print("=" * 60)

    session = "private_session"

    # Alice adds private contact
    print("\n--- Alice adds private contact ---\n")
    private_agent.print_response(
        "Add my personal contact: Dr. Smith is my therapist. "
        "Appointments on Tuesdays at 3pm.",
        user_id="alice@example.com",
        session_id=session + "_alice",
        stream=True,
    )

    # Bob cannot see Alice's contact
    print("\n--- Bob tries to query ---\n")
    private_agent.print_response(
        "What do you know about Dr. Smith?",
        user_id="bob@example.com",
        session_id=session + "_bob",
        stream=True,
    )

    # Alice can see her own data
    print("\n--- Alice queries her own data ---\n")
    private_agent.print_response(
        "What do you know about Dr. Smith?",
        user_id="alice@example.com",
        session_id=session + "_alice_2",
        stream=True,
    )

    print("\n💡 User namespace: Each user has private entity data")


# ============================================================================
# Demo: Team Namespaces
# ============================================================================
def demo_team_namespaces():
    """Show custom team namespaces."""
    print("\n" + "=" * 60)
    print("Demo: Team Namespaces")
    print("=" * 60)

    session = "team_session"

    # Sales adds prospect
    print("\n--- Sales adds prospect ---\n")
    sales_agent.print_response(
        "Track this prospect: Acme Corp is in our pipeline. "
        "Budget: $500K, Decision maker: Jane Doe, Close date: Q2.",
        user_id="sales_rep@company.com",
        session_id=session + "_sales",
        stream=True,
    )

    # Engineering adds system info
    print("\n--- Engineering adds system info ---\n")
    engineering_agent.print_response(
        "Track this system: Payment Service runs on Kubernetes. "
        "SLA: 99.99%, Owner: Platform team, Tech: Go + PostgreSQL.",
        user_id="engineer@company.com",
        session_id=session + "_eng",
        stream=True,
    )

    # Sales can see sales data
    print("\n--- Sales queries their data ---\n")
    sales_agent.print_response(
        "What prospects are in our pipeline?",
        user_id="sales_rep@company.com",
        session_id=session + "_sales_2",
        stream=True,
    )

    # Engineering can see engineering data
    print("\n--- Engineering queries their data ---\n")
    engineering_agent.print_response(
        "What do we know about the Payment Service?",
        user_id="engineer@company.com",
        session_id=session + "_eng_2",
        stream=True,
    )

    # Cross-namespace: Sales cannot see engineering data
    print("\n--- Sales tries to query engineering data ---\n")
    sales_agent.print_response(
        "What systems does the Payment Service run on?",
        user_id="sales_rep@company.com",
        session_id=session + "_cross",
        stream=True,
    )

    print("\n💡 Team namespaces: Data isolated by department/team")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_global_sharing()
    demo_private_namespace()
    demo_team_namespaces()

    print("\n" + "=" * 60)
    print("✅ Namespace controls sharing boundaries")
    print('   "global" = shared with everyone')
    print('   "user" = private per user')
    print('   custom = team/department isolation')
    print("=" * 60)
