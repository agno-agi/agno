"""
Entity Memory: Namespace Sharing
================================
Private vs shared entity graphs.

Namespaces control who can see entity data:

- "user": Private per user (requires user_id)
- "global": Shared with everyone
- Custom: Explicit grouping (e.g., "sales_team", "engineering")

Run:
    python cookbook/15_learning/entity_memory/03_namespace_sharing.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")


# ============================================================================
# Three Agents with Different Namespaces
# ============================================================================

# Private per user
private_agent = Agent(
    name="Private Entity Agent",
    model=model,
    db=db,
    instructions="Track entities privately for each user.",
    learning=LearningMachine(
        db=db,
        model=model,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="user",  # Private per user
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

# Shared globally
global_agent = Agent(
    name="Global Entity Agent",
    model=model,
    db=db,
    instructions="Track entities shared with all users.",
    learning=LearningMachine(
        db=db,
        model=model,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",  # Shared with everyone
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

# Team-specific
sales_agent = Agent(
    name="Sales Team Agent",
    model=model,
    db=db,
    instructions="Track entities for the sales team.",
    learning=LearningMachine(
        db=db,
        model=model,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="sales_team",  # Team-specific
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Private Namespace
# ============================================================================
def demo_private_namespace():
    """Show private entities per user."""
    print("=" * 60)
    print("Demo: Private Namespace (per user)")
    print("=" * 60)

    # User Alice creates entities
    print("\n--- Alice creates an entity ---\n")
    private_agent.print_response(
        "Track my personal contact: John Smith, my mentor, email john@example.com",
        user_id="alice@example.com",
        session_id="alice_session",
        stream=True,
    )

    # User Bob tries to access
    print("\n--- Bob tries to find Alice's entities ---\n")
    private_agent.print_response(
        "What do you know about John Smith?",
        user_id="bob@example.com",
        session_id="bob_session",
        stream=True,
    )

    print("\n💡 Notice: Bob can't see Alice's private entities")


# ============================================================================
# Demo: Global Namespace
# ============================================================================
def demo_global_namespace():
    """Show globally shared entities."""
    print("\n" + "=" * 60)
    print("Demo: Global Namespace (shared)")
    print("=" * 60)

    # User Alice creates a global entity
    print("\n--- Alice creates a shared entity ---\n")
    global_agent.print_response(
        "Track company info: TechCorp Inc, industry: SaaS, employees: 500",
        user_id="alice@example.com",
        session_id="alice_global",
        stream=True,
    )

    # User Bob can see it
    print("\n--- Bob accesses the shared entity ---\n")
    global_agent.print_response(
        "What do you know about TechCorp Inc?",
        user_id="bob@example.com",
        session_id="bob_global",
        stream=True,
    )

    print("\n💡 Notice: Bob CAN see Alice's global entities")


# ============================================================================
# Demo: Team Namespace
# ============================================================================
def demo_team_namespace():
    """Show team-specific entities."""
    print("\n" + "=" * 60)
    print("Demo: Team Namespace (sales_team)")
    print("=" * 60)

    # Sales team member adds a lead
    print("\n--- Sales person adds a lead ---\n")
    sales_agent.print_response(
        "New lead: Prospect Corp, contact: Jane Doe, budget: $50K, stage: discovery",
        user_id="sales_rep@example.com",
        session_id="sales_session",
        stream=True,
    )

    # Another sales team member can see it
    print("\n--- Another sales person queries ---\n")
    sales_agent.print_response(
        "What's the status of Prospect Corp?",
        user_id="sales_manager@example.com",
        session_id="manager_session",
        stream=True,
    )


# ============================================================================
# Namespace Configuration Guide
# ============================================================================
def namespace_guide():
    """Print namespace configuration guide."""
    print("\n" + "=" * 60)
    print("Namespace Configuration Guide")
    print("=" * 60)
    print("""
PRIVATE PER USER:
   EntityMemoryConfig(namespace="user")
   
   - Each user has their own entity graph
   - Good for: personal contacts, private notes
   - Requires: user_id at runtime

GLOBAL (SHARED WITH ALL):
   EntityMemoryConfig(namespace="global")
   
   - Everyone sees the same entities
   - Good for: company knowledge, public info
   - Default if not specified

TEAM/GROUP:
   EntityMemoryConfig(namespace="sales_team")
   EntityMemoryConfig(namespace="engineering")
   
   - Group-specific entity graphs
   - Good for: department knowledge, project teams
   - Custom string = custom group

COMBINING NAMESPACES:
   You can run multiple agents with different namespaces:
   
   # Sales CRM agent
   sales_crm = Agent(
       learning=LearningMachine(
           entity_memory=EntityMemoryConfig(namespace="sales")
       )
   )
   
   # Engineering wiki agent  
   eng_wiki = Agent(
       learning=LearningMachine(
           entity_memory=EntityMemoryConfig(namespace="engineering")
       )
   )
   
   # Company-wide agent
   company = Agent(
       learning=LearningMachine(
           entity_memory=EntityMemoryConfig(namespace="global")
       )
   )
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_private_namespace()
    demo_global_namespace()
    demo_team_namespace()
    namespace_guide()

    print("\n" + "=" * 60)
    print("✅ Namespace controls entity visibility:")
    print("   'user' = private per user")
    print("   'global' = shared with everyone")
    print("   custom = team/group specific")
    print("=" * 60)
