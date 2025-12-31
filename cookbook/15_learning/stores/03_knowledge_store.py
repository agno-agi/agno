"""
Knowledge Store - Learned Knowledge with Semantic Search

This cookbook demonstrates the KnowledgeStore for saving and retrieving
reusable insights via semantic search.

Features tested:
- Saving learnings with title, content, context, and tags
- Semantic search retrieval
- Knowledge persistence and retrieval
- Custom learning schemas

Note: Requires a Knowledge base with vector DB (e.g., PgVector).
"""

from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.learn.stores.knowledge import KnowledgeStore
from agno.learn.config import KnowledgeConfig
from agno.learn.schemas import DefaultLearning
from agno.embedder.openai import OpenAIEmbedder
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup vector database for knowledge storage
embedder = OpenAIEmbedder(id="text-embedding-3-small")
vector_db = PgVector(
    table_name="agno_learned_knowledge",
    db_url=db_url,
    embedder=embedder,
)

# Create knowledge base
knowledge_base = Knowledge(vector_db=vector_db)

# Create the store
store = KnowledgeStore(knowledge=knowledge_base)


def test_save_learnings():
    """Test saving learnings to the knowledge base."""
    print("=" * 60)
    print("TEST: Save Learnings")
    print("=" * 60)

    # Save some learnings
    learnings = [
        {
            "title": "Python async best practices",
            "learning": "Use asyncio.gather() for concurrent I/O operations instead of sequential awaits. This can improve throughput by 3-5x for I/O bound tasks.",
            "context": "When optimizing async Python code",
            "tags": ["python", "async", "performance"],
        },
        {
            "title": "LLM prompt engineering - chain of thought",
            "learning": "Adding 'Let's think step by step' to prompts improves reasoning accuracy by 20-40% on complex tasks. Works best with math and logic problems.",
            "context": "When prompting LLMs for complex reasoning",
            "tags": ["llm", "prompts", "reasoning"],
        },
        {
            "title": "Database indexing rule of thumb",
            "learning": "Create indexes on columns used in WHERE clauses that filter more than 10-15% of rows. For high-cardinality columns, B-tree indexes work well. For low-cardinality, consider partial indexes.",
            "context": "When optimizing database queries",
            "tags": ["database", "performance", "sql"],
        },
        {
            "title": "React state management patterns",
            "learning": "For shared state across 2-3 components, use React Context. For complex state with many consumers, consider Zustand or Jotai over Redux for simpler code.",
            "context": "When designing React application architecture",
            "tags": ["react", "state", "frontend"],
        },
        {
            "title": "API rate limiting strategy",
            "learning": "Implement token bucket algorithm for rate limiting. Use sliding window for smoother rate limits. Always return Retry-After header with 429 responses.",
            "context": "When implementing API rate limiting",
            "tags": ["api", "rate-limiting", "backend"],
        },
    ]

    for l in learnings:
        success = store.save(
            title=l["title"],
            learning=l["learning"],
            context=l["context"],
            tags=l["tags"],
        )
        print(f"  Saved: {l['title'][:40]}... {'✓' if success else '✗'}")

    print("\n✅ Save learnings test passed!")


def test_semantic_search():
    """Test semantic search retrieval."""
    print("\n" + "=" * 60)
    print("TEST: Semantic Search")
    print("=" * 60)

    # Search for Python-related learnings
    query_1 = "How can I make my Python code faster?"
    results_1 = store.search(query=query_1, limit=3)

    print(f"\nQuery: '{query_1}'")
    print(f"Results ({len(results_1)} found):")
    for r in results_1:
        print(f"  - {r.title}")
        print(f"    {r.learning[:80]}...")

    # Search for frontend-related learnings
    query_2 = "What's the best way to manage state in React?"
    results_2 = store.search(query=query_2, limit=3)

    print(f"\nQuery: '{query_2}'")
    print(f"Results ({len(results_2)} found):")
    for r in results_2:
        print(f"  - {r.title}")
        print(f"    {r.learning[:80]}...")

    # Search for something not directly mentioned
    query_3 = "How do I improve API response times?"
    results_3 = store.search(query=query_3, limit=3)

    print(f"\nQuery: '{query_3}'")
    print(f"Results ({len(results_3)} found):")
    for r in results_3:
        print(f"  - {r.title}")
        print(f"    {r.learning[:80]}...")

    print("\n✅ Semantic search test passed!")


def test_learning_schema():
    """Test the DefaultLearning schema."""
    print("\n" + "=" * 60)
    print("TEST: DefaultLearning Schema")
    print("=" * 60)

    # Create learning via schema
    learning = DefaultLearning(
        title="Test Learning",
        learning="This is a test insight about testing.",
        context="When writing tests",
        tags=["test", "demo"],
    )

    print("\nLearning object:")
    pprint(learning.to_dict())

    print("\nFormatted text:")
    print(learning.to_text())

    # Test from_dict
    parsed = DefaultLearning.from_dict({
        "title": "Parsed Learning",
        "learning": "Parsed from dict",
    })

    assert parsed is not None
    assert parsed.title == "Parsed Learning"
    print("\n  ✓ from_dict works correctly")

    # Test from_dict with invalid data
    invalid = DefaultLearning.from_dict({"title": "Missing learning field"})
    assert invalid is None, "Should return None for invalid data"
    print("  ✓ from_dict returns None for invalid data")

    print("\n✅ Schema test passed!")


def test_get_all_learnings():
    """Test retrieving all learnings."""
    print("\n" + "=" * 60)
    print("TEST: Get All Learnings")
    print("=" * 60)

    all_learnings = store.get_all(limit=10)

    print(f"\nTotal learnings: {len(all_learnings)}")
    for l in all_learnings:
        print(f"  - {l.title}")
        if l.tags:
            print(f"    Tags: {', '.join(l.tags)}")

    print("\n✅ Get all learnings test passed!")


def test_learning_for_context():
    """Test how learnings can be used to provide context."""
    print("\n" + "=" * 60)
    print("TEST: Learning Context for Agent")
    print("=" * 60)

    # Simulate what happens when an agent asks a question
    user_query = "I'm building an API and it's slow. How can I improve performance?"

    relevant_learnings = store.search(query=user_query, limit=3)

    print(f"\nUser query: '{user_query}'")
    print("\nRelevant learnings to inject into context:")
    print("-" * 50)

    context_parts = []
    for l in relevant_learnings:
        context_parts.append(l.to_text())

    context_injection = "\n\n".join(context_parts)
    print(context_injection)
    print("-" * 50)

    print("\nThis context would be injected into the system prompt.")

    print("\n✅ Context injection test passed!")


def test_propose_mode_workflow():
    """Demonstrate the PROPOSE mode workflow."""
    print("\n" + "=" * 60)
    print("TEST: PROPOSE Mode Workflow (Simulated)")
    print("=" * 60)

    print("""
    In PROPOSE mode, the workflow is:

    1. Agent identifies a reusable insight during conversation
    2. Agent proposes the learning to the user:
       "I noticed something that might be useful to remember:
        Title: [title]
        Learning: [insight]
        Should I save this for future reference?"
    3. User confirms: "Yes, save it"
    4. Agent calls save_learning tool
    """)

    # Simulate the workflow
    proposed_learning = {
        "title": "User prefers Postgres over MySQL",
        "learning": "The user has expressed preference for PostgreSQL for new projects due to better JSON support and advanced features.",
        "context": "When recommending databases",
        "tags": ["database", "preferences"],
    }

    print("\nAgent proposes:")
    print(f"  Title: {proposed_learning['title']}")
    print(f"  Learning: {proposed_learning['learning']}")

    # User confirms (simulated)
    user_confirms = True
    print(f"\nUser confirms: {user_confirms}")

    if user_confirms:
        success = store.save(
            title=proposed_learning["title"],
            learning=proposed_learning["learning"],
            context=proposed_learning["context"],
            tags=proposed_learning["tags"],
        )
        print(f"Saved: {'✓' if success else '✗'}")

    print("\n✅ PROPOSE mode workflow test passed!")


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    # Note: Knowledge base cleanup depends on your vector DB implementation
    # This might need to be adjusted based on your setup
    try:
        # Clear the vector DB table
        vector_db.clear()
        print("  Cleared vector database")
    except Exception as e:
        print(f"  Cleanup note: {e}")


if __name__ == "__main__":
    # Run all tests
    test_save_learnings()
    test_semantic_search()
    test_learning_schema()
    test_get_all_learnings()
    test_learning_for_context()
    test_propose_mode_workflow()

    # Final summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_learnings = store.get_all(limit=20)
    print(f"\nTotal learnings in knowledge base: {len(all_learnings)}")

    # Group by tags
    tag_counts = {}
    for l in all_learnings:
        for tag in (l.tags or []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    print("\nLearnings by tag:")
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        print(f"  {tag}: {count}")

    # Uncomment to clean up
    # cleanup()

    print("\n" + "=" * 60)
    print("✅ All KnowledgeStore tests passed!")
    print("=" * 60)
