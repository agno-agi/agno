"""
Knowledge Store Cookbook
========================

"Knowledge is power." - Francis Bacon

This cookbook demonstrates the KnowledgeStore - a system for capturing
reusable insights that apply across conversations and users. Unlike
user profiles (per-person) or session context (per-conversation),
knowledge is shared and retrieved via semantic search.

Think of it as:
- UserProfile = "Alice prefers Python" (about a person)
- SessionContext = "We're debugging a login bug" (about a moment)
- Knowledge = "Always check for null before dereferencing" (universal wisdom)

Tests:
1. Save and search - The core workflow
2. Semantic search - Find by meaning, not keywords
3. Agent tool - Let agents save learnings
4. Tags and context - Organize knowledge
5. Format for prompt - Inject into system prompts
6. Delete learnings - Remove outdated knowledge
7. Agent/team filtering - Scope knowledge to contexts
8. State tracking - Know when knowledge was saved
9. Multiple learnings - Build up a knowledge base
10. Relevant context - Get formatted learnings for queries
"""

from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import KnowledgeConfig, KnowledgeStore
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, learnings_table="agno_learnings")
model = OpenAIResponses(id="gpt-5.2")

# Vector database for semantic search
vector_db = PgVector(
    table_name="agno_learned_knowledge",
    db_url=db_url,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    search_type=SearchType.hybrid,
)

# Knowledge base
knowledge_base = Knowledge(
    name="Knowledge Store",
    vector_db=vector_db,
)

# Knowledge store
store = KnowledgeStore(
    config=KnowledgeConfig(
        knowledge=knowledge_base,
        enable_tool=True,
        enable_add=True,
        enable_delete=True,
    )
)

# Setup logging (only needed when using store directly, not through LearningMachine)
store.set_log_level()

# -----------------------------------------------------------------------------
# Test 1: Save and Search
# -----------------------------------------------------------------------------


def test_save_and_search():
    """
    The core workflow: save a learning, then find it via search.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Save and Search")
    print("=" * 60)

    # Save a learning
    success = store.save(
        title="Python exception handling",
        learning="Always catch specific exceptions, never bare except clauses",
        context="When writing production Python code",
        tags=["python", "exceptions", "best-practices"],
    )
    print(f"\n📝 Save result: {success}")

    # Search for it
    results = store.search(query="How should I handle errors in Python?")
    print(f"\n🔍 Search results: {len(results)} found")
    for r in results:
        print(f"   - {r.title}: {r.learning[:50]}...")

    print("\n✅ Save and search works")


# -----------------------------------------------------------------------------
# Test 2: Semantic Search
# -----------------------------------------------------------------------------


def test_semantic_search():
    """
    Search finds learnings by meaning, not exact keywords.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Semantic Search")
    print("=" * 60)

    # Save some learnings
    store.save(
        title="Database connection pooling",
        learning="Use connection pooling to avoid opening new connections for each query",
        context="When working with SQL databases in production",
        tags=["database", "performance"],
    )

    store.save(
        title="API rate limiting",
        learning="Implement exponential backoff when hitting rate limits",
        context="When calling external APIs",
        tags=["api", "reliability"],
    )

    # Search with different phrasings
    queries = [
        "My database queries are slow",  # Should find connection pooling
        "API keeps returning 429 errors",  # Should find rate limiting
        "How to improve SQL performance",  # Should find connection pooling
    ]

    for query in queries:
        results = store.search(query=query, limit=2)
        print(f"\n🔍 Query: '{query}'")
        for r in results:
            print(f"   → {r.title}")

    print("\n✅ Semantic search finds relevant results")


# -----------------------------------------------------------------------------
# Test 3: Agent Tool
# -----------------------------------------------------------------------------


def test_agent_tool():
    """
    Give an agent the ability to save learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Agent Tool")
    print("=" * 60)

    # Get the tool (this would be given to an agent)
    save_learning = store.get_agent_tool()

    # Inspect the tool
    print(f"\n🔧 Tool name: {save_learning.__name__}")
    print(f"   Tool doc: {save_learning.__doc__[:100]}...")

    # Agent saves a learning
    result = save_learning(
        title="Async context managers",
        learning="Use 'async with' for resources that need async cleanup",
        context="When working with async I/O resources",
        tags=["python", "async"],
    )
    print(f"\n🔧 Tool result: {result}")
    print(f"🔄 Learning saved: {store.was_updated}")

    # Verify it's searchable
    results = store.search(query="async resource management")
    print(f"\n🔍 Found via search: {len(results)} results")

    print("\n✅ Agent tool works")


# -----------------------------------------------------------------------------
# Test 4: Tags and Context
# -----------------------------------------------------------------------------


def test_tags_and_context():
    """
    Tags and context help organize and explain learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Tags and Context")
    print("=" * 60)

    # Save with rich metadata
    store.save(
        title="CSS Grid vs Flexbox",
        learning="Use Grid for 2D layouts, Flexbox for 1D. Grid for page layout, Flexbox for components.",
        context="When deciding between CSS layout methods",
        tags=["css", "frontend", "layout", "web"],
    )

    # Search and see the context
    results = store.search(query="Which CSS layout should I use?")
    for r in results:
        print(f"\n📋 {r.title}")
        print(f"   Learning: {r.learning}")
        print(f"   Context: {r.context}")
        print(f"   Tags: {r.tags}")

    print("\n✅ Tags and context preserved")


# -----------------------------------------------------------------------------
# Test 5: Format for Prompt
# -----------------------------------------------------------------------------


def test_format_for_prompt():
    """
    Get formatted learnings for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Format for Prompt")
    print("=" * 60)

    # Save a few learnings
    store.save(
        title="Git commit messages",
        learning="Use imperative mood: 'Add feature' not 'Added feature'",
        context="When writing commit messages",
    )

    store.save(
        title="Git branch naming",
        learning="Use prefixes like feature/, bugfix/, hotfix/ for clarity",
        context="When creating branches",
    )

    # Search
    results = store.search(query="Git best practices", limit=3)

    # Format for injection
    formatted = store.format_for_prompt(data=results)
    print(f"\n📝 Formatted for system prompt:")
    print("-" * 40)
    print(formatted)
    print("-" * 40)

    # Should be XML formatted
    assert "<relevant_learnings>" in formatted
    assert "</relevant_learnings>" in formatted

    print("\n✅ Format for prompt works")


# -----------------------------------------------------------------------------
# Test 6: Delete Learnings
# -----------------------------------------------------------------------------


def test_delete_learnings():
    """
    Remove outdated or incorrect learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Delete Learnings")
    print("=" * 60)

    # Save something
    store.save(
        title="Temporary learning",
        learning="This will be deleted",
    )

    # Verify it exists
    results = store.search(query="temporary learning")
    print(f"\n📋 Before delete: {len(results)} results")

    # Delete it
    deleted = store.delete(title="Temporary learning")
    print(f"🗑️  Delete result: {deleted}")

    # Verify it's gone
    results = store.search(query="temporary learning")
    print(f"📋 After delete: {len(results)} results")

    print("\n✅ Delete works")


# -----------------------------------------------------------------------------
# Test 7: Agent/Team Filtering
# -----------------------------------------------------------------------------


def test_agent_team_filtering():
    """
    Scope learnings to specific agents or teams.
    """
    print("\n" + "=" * 60)
    print("TEST 7: Agent/Team Filtering")
    print("=" * 60)

    # Save learnings for different agents
    store.save(
        title="Code review checklist",
        learning="Check for security, performance, and readability",
        agent_id="code_reviewer",
    )

    store.save(
        title="Support ticket triage",
        learning="Categorize by urgency and impact first",
        agent_id="support_agent",
    )

    # Search with agent filter
    code_results = store.search(query="review checklist", agent_id="code_reviewer")
    support_results = store.search(query="ticket process", agent_id="support_agent")

    print(f"\n👨‍💻 Code reviewer's learnings: {len(code_results)}")
    for r in code_results:
        print(f"   - {r.title}")

    print(f"\n🎧 Support agent's learnings: {len(support_results)}")
    for r in support_results:
        print(f"   - {r.title}")

    print("\n✅ Agent filtering works")


# -----------------------------------------------------------------------------
# Test 8: State Tracking
# -----------------------------------------------------------------------------


def test_state_tracking():
    """
    Know when a learning was saved.
    """
    print("\n" + "=" * 60)
    print("TEST 8: State Tracking")
    print("=" * 60)

    # Reset state
    store.learning_saved = False

    # Save via agent tool
    save_learning = store.get_agent_tool()
    save_learning(
        title="State tracking test",
        learning="This tests the was_updated property",
    )

    print(f"\n📝 After save: was_updated = {store.was_updated}")
    assert store.was_updated, "Should be updated"

    print("\n✅ State tracking works")


# -----------------------------------------------------------------------------
# Test 9: Multiple Learnings
# -----------------------------------------------------------------------------


def test_multiple_learnings():
    """
    Build up a knowledge base with many learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 9: Multiple Learnings")
    print("=" * 60)

    # A batch of learnings
    learnings = [
        {
            "title": "REST API versioning",
            "learning": "Use URL versioning (/v1/) for public APIs, header versioning for internal",
            "tags": ["api", "rest"],
        },
        {
            "title": "Docker layer caching",
            "learning": "Put frequently changing steps last in Dockerfile to maximize cache hits",
            "tags": ["docker", "performance"],
        },
        {
            "title": "Testing pyramid",
            "learning": "More unit tests, fewer integration tests, even fewer E2E tests",
            "tags": ["testing", "architecture"],
        },
        {
            "title": "Environment variables",
            "learning": "Never commit secrets. Use .env files locally, secret managers in prod",
            "tags": ["security", "devops"],
        },
    ]

    # Save all
    for l in learnings:
        store.save(**l)
        print(f"   ✓ Saved: {l['title']}")

    # Search across all
    results = store.search(query="How do I improve my development workflow?", limit=5)
    print(f"\n🔍 Found {len(results)} relevant learnings")

    print("\n✅ Multiple learnings work")


# -----------------------------------------------------------------------------
# Test 10: Relevant Context
# -----------------------------------------------------------------------------


def test_relevant_context():
    """
    Get pre-formatted context for a query.
    """
    print("\n" + "=" * 60)
    print("TEST 10: Relevant Context")
    print("=" * 60)

    # Add some learnings
    store.save(
        title="Logging best practices",
        learning="Log at appropriate levels: DEBUG for dev, INFO for prod, ERROR for failures",
        context="When implementing application logging",
    )

    # Get relevant context (combines search + format)
    context = store.get_relevant_context(
        query="How should I log in my application?",
        limit=3,
    )

    print(f"\n📝 Relevant context for 'logging' query:")
    print("-" * 40)
    print(context)
    print("-" * 40)

    print("\n✅ Relevant context works")


# -----------------------------------------------------------------------------
# Test 11: Recall (Protocol Method)
# -----------------------------------------------------------------------------


def test_recall():
    """
    Test the recall method (LearningStore protocol).
    """
    print("\n" + "=" * 60)
    print("TEST 11: Recall (Protocol Method)")
    print("=" * 60)

    # recall() is what LearningMachine calls
    results = store.recall(message="What are some Python tips?", limit=3)

    print(f"\n📋 Recall results: {len(results) if results else 0}")
    if results:
        for r in results:
            print(f"   - {r.title}")

    # Also works with query parameter
    results2 = store.recall(query="database performance", limit=3)
    print(f"\n📋 Recall with query: {len(results2) if results2 else 0}")

    print("\n✅ Recall works")


# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    titles_to_delete = [
        "Python exception handling",
        "Database connection pooling",
        "API rate limiting",
        "Async context managers",
        "CSS Grid vs Flexbox",
        "Git commit messages",
        "Git branch naming",
        "Temporary learning",
        "Code review checklist",
        "Support ticket triage",
        "State tracking test",
        "REST API versioning",
        "Docker layer caching",
        "Testing pyramid",
        "Environment variables",
        "Logging best practices",
    ]

    for title in titles_to_delete:
        try:
            store.delete(title=title)
        except Exception:
            pass

    print("🧹 Cleaned")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("🧠 KnowledgeStore Cookbook")
    print("   Knowledge is power")
    print("=" * 60)

    # Run tests
    test_save_and_search()
    # test_semantic_search()
    # test_agent_tool()
    # test_tags_and_context()
    # test_format_for_prompt()
    # test_delete_learnings()
    # test_agent_team_filtering()
    # test_state_tracking()
    # test_multiple_learnings()
    # test_relevant_context()
    # test_recall()

    # Cleanup
    cleanup()

    print("\n" + "=" * 60)
    print("✅ All tests complete")
    print("   Key insight: Knowledge is SHARED and SEMANTIC")
    print("   - UserProfile: per-person, exact lookup")
    print("   - SessionContext: per-session, exact lookup")
    print("   - Knowledge: shared, semantic search")
    print("=" * 60)
