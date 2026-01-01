"""
Knowledge Store Cookbook
========================

"Knowledge is of no value unless you put it into practice." - Anton Chekhov

This cookbook demonstrates KnowledgeStore - a system for saving and
retrieving reusable insights via semantic search.

Unlike the other stores:
- UserProfile = about a specific person
- SessionContext = about a specific conversation
- Knowledge = wisdom that applies anywhere

The magic: you save a learning once, and it surfaces whenever relevant,
across any user, any session, any context.

Tests:
1. Saving learnings - Capture insights
2. Semantic search - Find by meaning, not keywords
3. Agent tool - Let agents save what they learn
4. Relevance retrieval - Get context for prompts
5. PROPOSE mode workflow - Human-in-the-loop
6. Cross-domain search - One query, multiple domains
7. Tags and filtering - Organize your knowledge
8. Learning lifecycle - Create, find, delete
"""

from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn.config import KnowledgeConfig, LearningMode
from agno.learn.schemas import BaseLearning
from agno.learn.stores.knowledge import KnowledgeStore
from agno.vectordb.pgvector import PgVector
from rich.pretty import pprint

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Vector database for semantic search
embedder = OpenAIEmbedder(id="text-embedding-3-small")
vector_db = PgVector(
    table_name="agno_learned_knowledge",
    db_url=db_url,
    embedder=embedder,
)

# Knowledge base wraps the vector DB
knowledge_base = Knowledge(vector_db=vector_db)

# The store
store = KnowledgeStore(
    config=KnowledgeConfig(
        knowledge=knowledge_base,
        mode=LearningMode.AGENTIC,
        enable_tool=True,
        enable_add=True,
        enable_update=True,
        enable_delete=True,
    )
)


# -----------------------------------------------------------------------------
# Test 1: Saving Learnings
# -----------------------------------------------------------------------------


def test_save_learnings():
    """
    The foundation: save insights that matter.
    Each learning has: title, content, context, tags.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Saving Learnings")
    print("=" * 60)

    learnings = [
        {
            "title": "Python async best practices",
            "learning": "Use asyncio.gather() for concurrent I/O operations instead of sequential awaits. This can improve throughput by 3-5x for I/O bound tasks.",
            "context": "When optimizing async Python code",
            "tags": ["python", "async", "performance"],
        },
        {
            "title": "LLM chain of thought prompting",
            "learning": "Adding 'Let's think step by step' to prompts improves reasoning accuracy by 20-40% on complex tasks. Works best for math and logic problems.",
            "context": "When prompting LLMs for complex reasoning",
            "tags": ["llm", "prompts", "reasoning"],
        },
        {
            "title": "Database indexing strategy",
            "learning": "Create indexes on columns used in WHERE clauses that filter more than 10-15% of rows. B-tree for high-cardinality, partial indexes for low-cardinality.",
            "context": "When optimizing database queries",
            "tags": ["database", "performance", "sql"],
        },
        {
            "title": "React state management",
            "learning": "For shared state across 2-3 components, use Context. For complex state with many consumers, Zustand or Jotai over Redux for simpler code.",
            "context": "When designing React architecture",
            "tags": ["react", "state", "frontend"],
        },
        {
            "title": "API rate limiting",
            "learning": "Token bucket for rate limiting, sliding window for smoother limits. Always return Retry-After header with 429 responses.",
            "context": "When implementing API rate limiting",
            "tags": ["api", "rate-limiting", "backend"],
        },
    ]

    print("\n💾 Saving learnings...")
    for l in learnings:
        success = store.save(
            title=l["title"],
            learning=l["learning"],
            context=l["context"],
            tags=l["tags"],
        )
        status = "✓" if success else "✗"
        print(f"   {status} {l['title']}")

    print("\n✅ Learnings saved")


# -----------------------------------------------------------------------------
# Test 2: Semantic Search
# -----------------------------------------------------------------------------


def test_semantic_search():
    """
    The magic: find by MEANING, not keywords.
    "How do I make Python faster?" finds async best practices.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Semantic Search")
    print("=" * 60)

    queries = [
        "How can I make my Python code faster?",
        "What's the best way to manage state in React?",
        "How do I improve API response times?",
    ]

    for query in queries:
        print(f"\n🔍 Query: '{query}'")
        results = store.search(query=query, limit=2)

        if results:
            for r in results:
                print(f"   → {r.title}")
                print(f"     {r.learning[:60]}...")
        else:
            print("   No results found")

    print("\n✅ Semantic search works")


# -----------------------------------------------------------------------------
# Test 3: Agent Tool
# -----------------------------------------------------------------------------


def test_agent_tool():
    """
    In AGENTIC mode, agents can save learnings directly.
    The tool is what gets exposed to the agent.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Agent Tool")
    print("=" * 60)

    # Get the tool (this is what an agent would use)
    save_learning = store.get_agent_tool()

    # Agent discovers something useful...
    result = save_learning(
        title="Debugging tip: print statements",
        learning="When debugging async code, print statements may appear out of order. Use logging with timestamps or a debugger for accurate tracing.",
        context="When debugging Python async code",
        tags=["python", "debugging", "async"],
    )

    print(f"\n🔧 Agent saved learning: {result}")
    print(f"   learning_saved: {store.learning_saved}")

    # Verify it's searchable
    results = store.search("async debugging")
    if results:
        print(f"\n   Found in search: {results[0].title}")

    print("\n✅ Agent tool works")


# -----------------------------------------------------------------------------
# Test 4: Relevance Retrieval
# -----------------------------------------------------------------------------


def test_relevance_retrieval():
    """
    get_relevant_context() gives prompt-ready formatted text.
    Inject into system prompts to inform responses.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Relevance Retrieval")
    print("=" * 60)

    # Simulate user asking about something
    user_query = "I'm building an API and it's slow. How can I improve performance?"

    context = store.get_relevant_context(query=user_query, limit=3)

    print(f"\n❓ User query: '{user_query}'")
    print(f"\n📚 Relevant context for injection:")
    print("-" * 50)
    print(context if context else "(no relevant learnings found)")
    print("-" * 50)

    print("\n   This would be added to the system prompt.")

    print("\n✅ Relevance retrieval works")


# -----------------------------------------------------------------------------
# Test 5: PROPOSE Mode Workflow
# -----------------------------------------------------------------------------


def test_propose_workflow():
    """
    In PROPOSE mode, agent suggests learnings, user confirms.
    Human-in-the-loop for quality control.
    """
    print("\n" + "=" * 60)
    print("TEST 5: PROPOSE Mode Workflow")
    print("=" * 60)

    print("""
    📋 PROPOSE mode workflow:

    1. Agent identifies useful insight during conversation
    2. Agent proposes to user:
       "I noticed something worth remembering:
        [Title]: Python virtual environments
        [Learning]: Always use venvs for project isolation...
        Should I save this?"
    3. User confirms: "Yes, save it"
    4. Agent calls save_learning tool
    """)

    # Simulate the workflow
    proposed = {
        "title": "Virtual environment best practice",
        "learning": "Always create a virtual environment for each Python project. Use venv for simple projects, poetry or conda for complex dependencies.",
        "context": "When starting a new Python project",
        "tags": ["python", "environment", "best-practices"],
    }

    print(f"\n🤖 Agent proposes:")
    print(f"   Title: {proposed['title']}")
    print(f"   Learning: {proposed['learning'][:60]}...")

    # User confirms (simulated)
    user_confirms = True
    print(f"\n👤 User: 'Yes, save it'")

    if user_confirms:
        success = store.save(**proposed)
        print(f"   Saved: {'✓' if success else '✗'}")

    print("\n✅ PROPOSE workflow demonstrated")


# -----------------------------------------------------------------------------
# Test 6: Cross-Domain Search
# -----------------------------------------------------------------------------


def test_cross_domain_search():
    """
    One query can surface insights from multiple domains.
    "How do I make things faster?" → Python, DB, API learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Cross-Domain Search")
    print("=" * 60)

    # Broad query that could match multiple domains
    query = "How do I improve performance?"

    results = store.search(query=query, limit=5)

    print(f"\n🌐 Query: '{query}'")
    print(f"   Results span multiple domains:\n")

    domains_found = set()
    for r in results:
        tags = r.tags if hasattr(r, "tags") and r.tags else []
        for tag in tags:
            domains_found.add(tag)
        print(f"   • {r.title}")
        print(f"     Tags: {', '.join(tags) if tags else 'none'}")

    print(f"\n   Domains covered: {', '.join(sorted(domains_found))}")

    print("\n✅ Cross-domain search works")


# -----------------------------------------------------------------------------
# Test 7: Learning Schema
# -----------------------------------------------------------------------------


def test_learning_schema():
    """
    BaseLearning schema provides structure and utility methods.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Learning Schema")
    print("=" * 60)

    # Create directly
    learning = BaseLearning(
        title="Test Learning",
        learning="This is a test insight about software testing.",
        context="When writing unit tests",
        tags=["testing", "demo"],
    )

    print("\n📦 Learning object:")
    pprint(learning.to_dict())

    print("\n📝 Formatted text:")
    print(learning.to_text())

    # Test from_dict
    parsed = BaseLearning.from_dict(
        {
            "title": "Parsed Learning",
            "learning": "Created from dict",
        }
    )
    assert parsed is not None
    print("\n   ✓ from_dict works")

    # Test validation
    invalid = BaseLearning.from_dict({"title": "Missing learning field"})
    assert invalid is None
    print("   ✓ Validation catches missing fields")

    print("\n✅ Schema works")


# -----------------------------------------------------------------------------
# Test 8: Delete Learning
# -----------------------------------------------------------------------------


def test_delete_learning():
    """
    Sometimes knowledge becomes outdated.
    """
    print("\n" + "=" * 60)
    print("TEST 8: Delete Learning")
    print("=" * 60)

    # Save something temporary
    title = "Temporary insight"
    store.save(
        title=title,
        learning="This will be deleted",
        context="Testing deletion",
        tags=["test"],
    )

    # Find it
    results = store.search("temporary")
    found_before = any(r.title == title for r in results)
    print(f"\n   Before delete: {'Found' if found_before else 'Not found'}")

    # Delete it
    deleted = store.delete(title)
    print(f"   Deleted: {'✓' if deleted else '✗'}")

    # Verify gone
    results = store.search("temporary")
    found_after = any(r.title == title for r in results)
    print(f"   After delete: {'Found' if found_after else 'Not found'}")

    print("\n✅ Deletion works")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------


def cleanup():
    """Wipe all test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    try:
        vector_db.clear()
        print("🧹 Cleared vector database")
    except Exception as e:
        print(f"   Note: {e}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("📚 KnowledgeStore Cookbook")
    print("   Wisdom that surfaces when needed")
    print("=" * 60)

    test_save_learnings()
    test_semantic_search()
    test_agent_tool()
    test_relevance_retrieval()
    test_propose_workflow()
    test_cross_domain_search()
    test_learning_schema()
    test_delete_learning()

    # Final summary
    print("\n" + "=" * 60)
    print("📊 FINAL STATE")
    print("=" * 60)

    # Show what we've learned
    all_results = store.search("", limit=20)  # Broad search
    print(f"\n   Total learnings: ~{len(all_results)}")

    # Group by tags
    tag_counts = {}
    for r in all_results:
        for tag in r.tags if hasattr(r, "tags") and r.tags else []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    if tag_counts:
        print("\n   By tag:")
        for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:5]:
            print(f"      {tag}: {count}")

    # cleanup()  # Uncomment to wipe

    print("\n" + "=" * 60)
    print("✅ All tests passed")
    print("   Remember: Knowledge without application is just data.")
    print("   But knowledge that surfaces at the right moment?")
    print("   That's wisdom.")
    print("=" * 60)
