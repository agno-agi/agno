"""
Entity Memory: Relationships
============================
Graph edges between entities.

Relationships connect entities to each other, forming a knowledge graph:
- "Bob is CTO of Acme"
- "Acme acquired StartupX"
- "Project Alpha depends on Service Beta"

Relationships have:
- Source entity (the "from" side)
- Target entity (the "to" side)
- Relation type (the edge label)
- Direction (incoming, outgoing, bidirectional)

Run:
    python cookbook/15_learning/entity_memory/02_entity_relationships.py
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
# Agent with Entity Memory
# ============================================================================
agent = Agent(
    name="Entity Relationships Agent",
    model=model,
    db=db,
    instructions="""\
You build a knowledge graph of entities and their relationships.

When users describe connections between entities:
1. Create entities if they don't exist
2. Add relationships between them
3. Use appropriate relation types

Common relation types:
- People: "works_at", "manages", "reports_to", "founded"
- Companies: "acquired", "partnered_with", "competes_with", "invested_in"
- Projects: "depends_on", "part_of", "maintained_by"

Track relationships bidirectionally when appropriate.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="relationships_demo",
            enable_agent_tools=True,
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
    print("Demo: People ↔ Companies")
    print("=" * 60)

    user = "rel_demo@example.com"
    session = "relationships_session"

    print("\n--- Define org structure ---\n")
    agent.print_response(
        "Let me tell you about TechCorp's leadership: "
        "Sarah Chen is the CEO and founder. "
        "Bob Martinez is the CTO, reporting to Sarah. "
        "Alice Kim leads Engineering under Bob. "
        "DevOps, Frontend, and Backend teams all report to Alice. "
        "Please track all these relationships.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query relationships
    print("\n--- Query relationships ---\n")
    agent.print_response(
        "Who reports to Alice Kim?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Company Relationships
# ============================================================================
def demo_company_relationships():
    """Show relationships between companies."""
    print("\n" + "=" * 60)
    print("Demo: Company ↔ Company")
    print("=" * 60)

    user = "company_rel@example.com"
    session = "company_session"

    print("\n--- Track company relationships ---\n")
    agent.print_response(
        "Some business relationships to track: "
        "BigTech acquired StartupAI for $500M. "
        "BigTech and MegaCorp are strategic partners. "
        "CloudCo competes with BigTech in the cloud space. "
        "Venture Capital firm TechFund invested in both StartupAI and CloudCo. "
        "Please save these relationships.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query
    print("\n--- Query: BigTech's relationships ---\n")
    agent.print_response(
        "What are all of BigTech's business relationships?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Project Dependencies
# ============================================================================
def demo_project_dependencies():
    """Show technical dependencies between projects."""
    print("\n" + "=" * 60)
    print("Demo: Project Dependencies")
    print("=" * 60)

    user = "deps_demo@example.com"
    session = "deps_session"

    print("\n--- Define project dependencies ---\n")
    agent.print_response(
        "Our system architecture: "
        "The API Gateway depends on Auth Service and Rate Limiter. "
        "User Service depends on Auth Service and Database Layer. "
        "Payment Service depends on User Service and external Stripe API. "
        "The mobile app depends on API Gateway. "
        "The web app also depends on API Gateway. "
        "Database Layer uses PostgreSQL. "
        "Track all these dependencies.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query dependencies
    print("\n--- Query: What depends on Auth Service? ---\n")
    agent.print_response(
        "What services depend on Auth Service?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Relationship Types Guide
# ============================================================================
def relationship_types_guide():
    """Print common relationship types."""
    print("\n" + "=" * 60)
    print("Common Relationship Types")
    print("=" * 60)
    print("""
PEOPLE ↔ ORGANIZATION:
   - works_at: Person works at company
   - founded: Person founded company
   - advises: Person advises company
   - invested_in: Person invested in company

PEOPLE ↔ PEOPLE:
   - reports_to: Reporting relationship
   - manages: Management relationship
   - mentors: Mentorship
   - collaborates_with: Peer collaboration

COMPANY ↔ COMPANY:
   - acquired: One acquired another
   - partnered_with: Strategic partnership
   - competes_with: Market competitors
   - invested_in: Investment relationship
   - subsidiary_of: Parent/child company

PROJECT ↔ PROJECT:
   - depends_on: Technical dependency
   - part_of: Component relationship
   - extends: Extension/plugin
   - replaces: Successor relationship

PROJECT ↔ PEOPLE:
   - maintained_by: Who maintains it
   - owned_by: Product owner
   - created_by: Original creator

DIRECTION:
   - incoming: Target → Source
   - outgoing: Source → Target  
   - bidirectional: Both ways
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_people_companies()
    demo_company_relationships()
    demo_project_dependencies()
    relationship_types_guide()

    print("\n" + "=" * 60)
    print("✅ Entity Relationships build a knowledge graph")
    print("   - Connect entities to entities")
    print("   - Track organization structures")
    print("   - Map dependencies and partnerships")
    print("=" * 60)
