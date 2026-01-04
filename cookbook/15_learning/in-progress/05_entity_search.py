"""
Entity Memory: Search
=====================
Finding entities by type, name, or content.

Entity Memory supports searching:
- By entity type (company, person, project)
- By name (exact or partial)
- By content (facts, events)
- Combined queries

The agent gets a `search_entities` tool that enables
natural language queries over the entity database.

Run:
    python cookbook/15_learning/entity_memory/05_entity_search.py
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
# Agent with Entity Search
# ============================================================================
agent = Agent(
    name="Entity Search Agent",
    model=model,
    db=db,
    instructions="""\
You help users find and explore information about entities.

You can:
- Search for entities by type (companies, people, projects)
- Search by name
- Search by content (facts, events)
- Answer questions about relationships

Use the search_entities tool to find relevant entities.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
            enable_agent_tools=True,
            agent_can_search_entities=True,  # Key: enable search
            agent_can_create_entity=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Setup: Populate Some Entities
# ============================================================================
def setup_entities():
    """Populate some entities for searching."""
    print("=" * 60)
    print("Setup: Populating entities for search demo")
    print("=" * 60)

    user = "search_setup@example.com"

    # Add companies
    agent.print_response(
        """Track these companies:
        - TechCorp: Enterprise SaaS, uses PostgreSQL, 500 employees, San Francisco
        - DataPipe: Real-time ETL, uses Kafka + Rust, 50 employees, Austin
        - CloudBase: Cloud infrastructure, uses Go + K8s, 200 employees, Seattle
        - AIStart: ML platform, uses Python + PyTorch, 30 employees, New York
        - SecureNet: Cybersecurity, uses Rust + C++, 100 employees, Boston""",
        user_id=user,
        session_id="setup_1",
        stream=True,
    )

    # Add people
    agent.print_response(
        """Track these people:
        - Alice Chen: CEO of TechCorp, background in finance
        - Bob Kumar: CTO of DataPipe, expert in distributed systems
        - Carol White: Founder of CloudBase, ex-Google
        - David Park: CEO of AIStart, Stanford AI PhD
        - Eve Martinez: CTO of SecureNet, former NSA""",
        user_id=user,
        session_id="setup_2",
        stream=True,
    )

    print("\n✅ Entities populated\n")


# ============================================================================
# Demo: Search by Type
# ============================================================================
def demo_search_by_type():
    """Search entities by their type."""
    print("=" * 60)
    print("Demo: Search by Entity Type")
    print("=" * 60)

    user = "search_demo@example.com"

    print("\n--- Search for all companies ---\n")
    agent.print_response(
        "List all the companies you know about.",
        user_id=user,
        session_id="type_search_1",
        stream=True,
    )

    print("\n--- Search for all people ---\n")
    agent.print_response(
        "Who are all the people in your records?",
        user_id=user,
        session_id="type_search_2",
        stream=True,
    )


# ============================================================================
# Demo: Search by Content
# ============================================================================
def demo_search_by_content():
    """Search entities by their facts/content."""
    print("\n" + "=" * 60)
    print("Demo: Search by Content")
    print("=" * 60)

    user = "content_search@example.com"

    print("\n--- Search: Companies using Rust ---\n")
    agent.print_response(
        "Which companies use Rust?",
        user_id=user,
        session_id="content_1",
        stream=True,
    )

    print("\n--- Search: Companies in California ---\n")
    agent.print_response(
        "What companies are based in California?",
        user_id=user,
        session_id="content_2",
        stream=True,
    )

    print("\n--- Search: People with AI/ML background ---\n")
    agent.print_response(
        "Who has a background in AI or machine learning?",
        user_id=user,
        session_id="content_3",
        stream=True,
    )


# ============================================================================
# Demo: Complex Queries
# ============================================================================
def demo_complex_queries():
    """Show more complex search queries."""
    print("\n" + "=" * 60)
    print("Demo: Complex Queries")
    print("=" * 60)

    user = "complex_search@example.com"

    print("\n--- Query: Small companies with strong tech ---\n")
    agent.print_response(
        "Which companies have fewer than 100 employees but use "
        "cutting-edge technology like Rust or distributed systems?",
        user_id=user,
        session_id="complex_1",
        stream=True,
    )

    print("\n--- Query: Leaders from big tech ---\n")
    agent.print_response(
        "Who are the founders or leaders with big tech backgrounds?",
        user_id=user,
        session_id="complex_2",
        stream=True,
    )

    print("\n--- Query: East coast vs West coast ---\n")
    agent.print_response(
        "Compare the companies on the East coast vs West coast.",
        user_id=user,
        session_id="complex_3",
        stream=True,
    )


# ============================================================================
# Demo: Relationship Queries
# ============================================================================
def demo_relationship_queries():
    """Search based on relationships."""
    print("\n" + "=" * 60)
    print("Demo: Relationship Queries")
    print("=" * 60)

    user = "rel_search@example.com"

    print("\n--- Query: Who leads which company ---\n")
    agent.print_response(
        "Create a list of who leads each company.",
        user_id=user,
        session_id="rel_1",
        stream=True,
    )

    print("\n--- Query: Find by role ---\n")
    agent.print_response(
        "Who are all the CTOs and what companies do they work for?",
        user_id=user,
        session_id="rel_2",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    setup_entities()
    demo_search_by_type()
    demo_search_by_content()
    demo_complex_queries()
    demo_relationship_queries()

    print("\n" + "=" * 60)
    print("✅ Entity search enables natural language queries")
    print("   Search by type, content, or relationships")
    print("   Combine criteria for complex queries")
    print("=" * 60)
