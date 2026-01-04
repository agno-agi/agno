"""
Entity Memory: Entity Search
============================
Query and find entities in the knowledge graph.

Entity Memory supports searching by:
- Entity type (company, person, project)
- Keywords in name/description
- Namespace filtering

Run:
    python cookbook/15_learning/entity_memory/05_entity_search.py
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
# Agent with Entity Search
# ============================================================================
agent = Agent(
    name="Entity Search Agent",
    model=model,
    db=db,
    instructions="""\
You help users manage and search their entity database.
Use search_entities to find entities by type or keywords.
Use entity tools to create and update entities.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="search_demo",
            enable_agent_tools=True,
            agent_can_search_entities=True,
            agent_can_create_entity=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Setup Test Data
# ============================================================================
def setup_test_data():
    """Create some entities for search demos."""
    print("=" * 60)
    print("Setup: Creating Test Entities")
    print("=" * 60)

    user = "search@example.com"

    # Create multiple entities
    entities = [
        "Create entity: TechCorp, type: company, industry: SaaS, location: San Francisco",
        "Create entity: DataInc, type: company, industry: Analytics, location: New York",
        "Create entity: CloudCo, type: company, industry: Infrastructure, location: Seattle",
        "Create entity: Alice Smith, type: person, role: CEO at TechCorp",
        "Create entity: Bob Johnson, type: person, role: CTO at DataInc",
        "Create entity: Project Phoenix, type: project, status: active",
        "Create entity: Project Neptune, type: project, status: planning",
    ]

    for entity in entities:
        print(f"\n--- {entity[:50]}... ---")
        agent.print_response(
            entity,
            user_id=user,
            session_id="setup",
            stream=False,
        )

    print("\n✅ Test entities created")


# ============================================================================
# Demo: Search by Type
# ============================================================================
def demo_search_by_type():
    """Search entities by their type."""
    print("\n" + "=" * 60)
    print("Demo: Search by Type")
    print("=" * 60)

    user = "search@example.com"

    print("\n--- Find all companies ---\n")
    agent.print_response(
        "Search for all entities of type 'company'",
        user_id=user,
        session_id="search_type_1",
        stream=True,
    )

    print("\n--- Find all people ---\n")
    agent.print_response(
        "Search for all person entities",
        user_id=user,
        session_id="search_type_2",
        stream=True,
    )

    print("\n--- Find all projects ---\n")
    agent.print_response(
        "Search for all project entities",
        user_id=user,
        session_id="search_type_3",
        stream=True,
    )


# ============================================================================
# Demo: Search by Keywords
# ============================================================================
def demo_search_by_keywords():
    """Search entities by keywords."""
    print("\n" + "=" * 60)
    print("Demo: Search by Keywords")
    print("=" * 60)

    user = "search@example.com"

    print("\n--- Search for 'Tech' ---\n")
    agent.print_response(
        "Search for entities containing 'Tech' in their name",
        user_id=user,
        session_id="search_kw_1",
        stream=True,
    )

    print("\n--- Search for 'CEO' ---\n")
    agent.print_response(
        "Find entities related to CEO",
        user_id=user,
        session_id="search_kw_2",
        stream=True,
    )


# ============================================================================
# Demo: Natural Language Search
# ============================================================================
def demo_natural_search():
    """Search using natural language."""
    print("\n" + "=" * 60)
    print("Demo: Natural Language Search")
    print("=" * 60)

    user = "search@example.com"

    print("\n--- 'What companies do we track?' ---\n")
    agent.print_response(
        "What companies do we track?",
        user_id=user,
        session_id="natural_1",
        stream=True,
    )

    print("\n--- 'Who works at TechCorp?' ---\n")
    agent.print_response(
        "Who works at TechCorp?",
        user_id=user,
        session_id="natural_2",
        stream=True,
    )

    print("\n--- 'What active projects do we have?' ---\n")
    agent.print_response(
        "What active projects do we have?",
        user_id=user,
        session_id="natural_3",
        stream=True,
    )


# ============================================================================
# Search API Guide
# ============================================================================
def search_api_guide():
    """Print the search API guide."""
    print("\n" + "=" * 60)
    print("Entity Search API")
    print("=" * 60)
    print("""
AGENT TOOL: search_entities

Parameters:
- query: Search keywords
- entity_type: Filter by type (optional)
- limit: Max results (optional)

Example agent calls:
  search_entities(query="TechCorp")
  search_entities(entity_type="company")
  search_entities(query="CEO", entity_type="person")

PROGRAMMATIC ACCESS:

store = agent.learning.entity_memory_store

# Search by query
results = store.search(
    query="Tech",
    namespace="my_namespace",
)

# Get specific entity
entity = store.get(
    entity_id="techcorp",
    entity_type="company",
    namespace="my_namespace",
)

# List all of a type
entities = store.list(
    entity_type="company",
    namespace="my_namespace",
)
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    setup_test_data()
    demo_search_by_type()
    demo_search_by_keywords()
    demo_natural_search()
    search_api_guide()

    print("\n" + "=" * 60)
    print("✅ Entity Search capabilities:")
    print("   - Search by type")
    print("   - Search by keywords")
    print("   - Natural language queries")
    print("=" * 60)
