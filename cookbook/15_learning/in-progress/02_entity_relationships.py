"""
Entity Memory: Relationships
============================
Graph edges between entities.

Relationships connect entities to each other:
- "Bob is CTO of Acme" (person → company)
- "Acme acquired StartupX" (company → company)
- "Project Alpha belongs to Engineering team" (project → team)

Relationships have:
- Source entity
- Target entity
- Relation type (e.g., "is_cto_of", "acquired", "belongs_to")
- Direction (incoming/outgoing)

This enables graph-like queries:
- "Who works at Acme?"
- "What companies has Bob been involved with?"
- "What projects are in the Engineering team?"

Run:
    python cookbook/15_learning/entity_memory/02_entity_relationships.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Entity Relationships
# ============================================================================
agent = Agent(
    name="Entity Relationships Agent",
    model=model,
    db=db,
    instructions="""\
You track entities and their relationships.

When users mention connections between entities, extract and save:
- The entities involved (create them if needed)
- The relationship between them
- The direction (who is related to whom)

Common relationship types:
- works_at, is_ceo_of, is_cto_of, founded
- acquired, invested_in, partners_with
- owns, created, manages
- reports_to, member_of

Be specific about relationship types - they enable graph queries later.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
            enable_agent_tools=True,
            agent_can_create_entity=True,
            enable_add_relationship=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: People and Companies
# ============================================================================
def demo_people_companies():
    """Show relationships between people and companies."""
    print("=" * 60)
    print("Demo: People ↔ Company Relationships")
    print("=" * 60)

    user = "rel_demo@example.com"
    session = "rel_session"

    # Establish relationships
    print("\n--- Establish org structure ---\n")
    agent.print_response(
        "Let me tell you about CloudTech Inc's leadership: "
        "Sarah Chen is the CEO. "
        "Marcus Rivera is the CTO. "
        "Priya Patel is the VP of Engineering who reports to Marcus. "
        "The company was founded by Sarah and her co-founder James Wong. "
        "Please track these relationships.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query relationships
    print("\n--- Query: Who leads CloudTech? ---\n")
    agent.print_response(
        "Who are the leaders at CloudTech Inc?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )

    print("\n--- Query: Marcus's relationships ---\n")
    agent.print_response(
        "What's Marcus Rivera's role and who reports to him?",
        user_id=user,
        session_id=session + "_3",
        stream=True,
    )


# ============================================================================
# Demo: Company Relationships
# ============================================================================
def demo_company_relationships():
    """Show relationships between companies."""
    print("\n" + "=" * 60)
    print("Demo: Company ↔ Company Relationships")
    print("=" * 60)

    user = "company_rel@example.com"
    session = "company_rel_session"

    # M&A and partnerships
    print("\n--- Corporate relationships ---\n")
    agent.print_response(
        "Some corporate news: "
        "MegaCorp acquired DataStartup for $500M last year. "
        "MegaCorp also has a strategic partnership with CloudProvider. "
        "DataStartup was originally spun out of BigTech. "
        "CloudProvider competes with both AWS and Azure. "
        "Track these company relationships.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query the graph
    print("\n--- Query: MegaCorp's network ---\n")
    agent.print_response(
        "What companies are connected to MegaCorp?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Project and Team Relationships
# ============================================================================
def demo_project_relationships():
    """Show relationships involving projects and teams."""
    print("\n" + "=" * 60)
    print("Demo: Project and Team Relationships")
    print("=" * 60)

    user = "project_rel@example.com"
    session = "project_session"

    # Project structure
    print("\n--- Project structure ---\n")
    agent.print_response(
        "Our project structure: "
        "Project Phoenix is owned by the Platform team. "
        "Alex leads Project Phoenix. "
        "Project Phoenix depends on the Auth Service. "
        "The Auth Service is maintained by the Security team. "
        "Both Platform and Security teams report to Engineering. "
        "Please map out these relationships.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query
    print("\n--- Query: Project Phoenix context ---\n")
    agent.print_response(
        "Tell me everything about Project Phoenix and its dependencies.",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Relationship Updates
# ============================================================================
def demo_relationship_changes():
    """Show how relationships can change over time."""
    print("\n" + "=" * 60)
    print("Demo: Relationship Changes")
    print("=" * 60)

    user = "change_rel@example.com"
    session = "change_session"

    # Initial state
    print("\n--- Initial state ---\n")
    agent.print_response(
        "John Smith is currently the CTO of TechCo.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Change
    print("\n--- Relationship change ---\n")
    agent.print_response(
        "Update: John Smith left TechCo. He's now the CEO of his new startup, InnovateLabs. "
        "TechCo promoted Lisa Wong to CTO.",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )

    # Verify
    print("\n--- Verify current state ---\n")
    agent.print_response(
        "Who is the current CTO of TechCo, and where is John Smith now?",
        user_id=user,
        session_id=session + "_3",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_people_companies()
    demo_company_relationships()
    demo_project_relationships()
    demo_relationship_changes()

    print("\n" + "=" * 60)
    print("✅ Entity relationships create a knowledge graph")
    print("   People ↔ Companies, Companies ↔ Companies")
    print("   Projects ↔ Teams, and more")
    print("=" * 60)
