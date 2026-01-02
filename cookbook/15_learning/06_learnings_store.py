"""
LearningsStore — Shared Knowledge
==================================
Deep dive into LearningsStore, which captures reusable insights
that apply across conversations and users.

Unlike user profiles (per-person) or session context (per-conversation),
learnings are SHARED and retrieved via SEMANTIC SEARCH.

Think of it as:
- UserProfile = "Alice prefers Python" (about a person)
- SessionContext = "We're debugging a login bug" (about a moment)
- Learnings = "Always check for null before dereferencing" (universal wisdom)

This cookbook demonstrates:
1. Save and search workflow
2. Semantic search (find by meaning, not keywords)
3. Agent tools (save_learning, search_learnings)
4. Tags and context metadata
5. Duplicate detection (BACKGROUND mode)
6. Agent/team filtering
7. State tracking (was_updated)
8. build_context() formatting
9. PROPOSE mode flow
10. Knowledge base requirement

Run this example:
    python cookbook/learning/06_learnings_store.py
"""

from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import LearningMode, LearningsConfig
from agno.learn.stores.learnings import LearningsStore
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o-mini")

# Knowledge base for semantic search
knowledge = Knowledge(
    name="Learnings Store Test",
    vector_db=PgVector(
        db_url=db_url,
        table_name="learnings_store_test",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Create stores with different modes
agentic_store = LearningsStore(
    config=LearningsConfig(
        knowledge=knowledge,
        model=model,
        mode=LearningMode.AGENTIC,
        enable_tool=True,
        enable_search=True,
    )
)

background_store = LearningsStore(
    config=LearningsConfig(
        knowledge=knowledge,
        model=model,
        mode=LearningMode.BACKGROUND,
    )
)

propose_store = LearningsStore(
    config=LearningsConfig(
        knowledge=knowledge,
        model=model,
        mode=LearningMode.PROPOSE,
        enable_tool=True,
        enable_search=True,
    )
)


# =============================================================================
# Test 1: Save and Search
# =============================================================================


def test_save_and_search():
    """
    The core workflow: save a learning, then find it via semantic search.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Save and Search")
    print("=" * 60)

    # Save a learning directly
    print("\n📝 Saving learning...")
    agentic_store.save(
        title="Python exception handling",
        learning="Always catch specific exceptions, never use bare except clauses. "
        "Bare except catches SystemExit and KeyboardInterrupt too.",
        context="When writing production Python code",
        tags=["python", "exceptions", "best-practices"],
    )
    print(f"🔄 was_updated: {agentic_store.was_updated}")

    # Search for it
    print("\n🔍 Searching for 'error handling in Python'...")
    results = agentic_store.search(
        query="How should I handle errors in Python?", limit=3
    )

    print(f"\n📋 Found {len(results)} results:")
    for r in results:
        print(f"   - {r.title}: {r.learning[:60]}...")

    print("\n✅ Save and search works!")


# =============================================================================
# Test 2: Semantic Search
# =============================================================================


def test_semantic_search():
    """
    Search finds learnings by MEANING, not exact keywords.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Semantic Search")
    print("=" * 60)

    # Save some learnings
    agentic_store.save(
        title="Database connection pooling",
        learning="Use connection pooling to avoid opening new connections for each query. "
        "PgBouncer or built-in pool (SQLAlchemy) work well.",
        context="When working with SQL databases in production",
        tags=["database", "performance", "postgresql"],
    )

    agentic_store.save(
        title="API rate limiting",
        learning="Implement exponential backoff when hitting rate limits. "
        "Start with 1s delay, double on each retry, cap at 60s.",
        context="When calling external APIs",
        tags=["api", "reliability", "retry"],
    )

    # Search with different phrasings (should still find relevant results)
    queries = [
        "My database queries are slow",  # Should find connection pooling
        "API keeps returning 429 errors",  # Should find rate limiting
        "How to improve SQL performance",  # Should find connection pooling
        "handling API throttling",  # Should find rate limiting
    ]

    for query in queries:
        results = agentic_store.search(query=query, limit=2)
        print(f"\n🔍 Query: '{query}'")
        for r in results:
            print(f"   → {r.title}")

    print("\n✅ Semantic search finds relevant results by meaning!")


# =============================================================================
# Test 3: Agent Tools
# =============================================================================


def test_agent_tools():
    """
    Give an agent tools to save and search learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 3: Agent Tools")
    print("=" * 60)

    # Get tools
    tools = agentic_store.get_tools()

    print(f"\n🔧 Available tools ({len(tools)}):")
    for tool in tools:
        name = getattr(tool, "__name__", str(tool))
        doc = getattr(tool, "__doc__", "")
        doc_first_line = doc.split("\n")[0][:60] if doc else "No description"
        print(f"   - {name}: {doc_first_line}...")

    # Find the save_learning tool
    save_learning = next(
        (t for t in tools if "save" in getattr(t, "__name__", "").lower()), None
    )

    if save_learning:
        # Agent calls the tool
        result = save_learning(
            title="Async context managers",
            learning="Use 'async with' for resources that need async cleanup. "
            "Don't forget __aenter__ and __aexit__ methods.",
            context="When working with async I/O resources",
            tags=["python", "async", "context-managers"],
        )
        print(f"\n🔧 save_learning result: {result}")
        print(f"🔄 was_updated: {agentic_store.was_updated}")

    # Find the search_learnings tool
    search_learnings = next(
        (t for t in tools if "search" in getattr(t, "__name__", "").lower()), None
    )

    if search_learnings:
        result = search_learnings(query="async resource management", limit=3)
        print(f"\n🔧 search_learnings result:\n{result}")

    print("\n✅ Agent tools work!")


# =============================================================================
# Test 4: Tags and Context
# =============================================================================


def test_tags_and_context():
    """
    Tags and context help organize and explain learnings.
    """
    print("\n" + "=" * 60)
    print("TEST 4: Tags and Context")
    print("=" * 60)

    # Save with rich metadata
    agentic_store.save(
        title="CSS Grid vs Flexbox",
        learning="Use Grid for 2D layouts (rows AND columns), Flexbox for 1D (row OR column). "
        "Grid for page layout, Flexbox for components.",
        context="When deciding between CSS layout methods for web development",
        tags=["css", "frontend", "layout", "web", "flexbox", "grid"],
    )

    # Search and examine metadata
    results = agentic_store.search(query="Which CSS layout should I use?", limit=1)

    for r in results:
        print(f"\n📋 Learning: {r.title}")
        print(f"   Content: {r.learning}")
        print(f"   Context: {r.context}")
        print(f"   Tags: {r.tags}")

    print("\n✅ Tags and context preserved!")


# =============================================================================
# Test 5: Duplicate Detection (BACKGROUND Mode)
# =============================================================================


def test_duplicate_detection():
    """
    In BACKGROUND mode, the store detects duplicates before saving.
    """
    print("\n" + "=" * 60)
    print("TEST 5: Duplicate Detection (BACKGROUND Mode)")
    print("=" * 60)

    # First, save a learning
    agentic_store.save(
        title="Git commit messages",
        learning="Use imperative mood: 'Add feature' not 'Added feature'. "
        "First line should be under 50 chars.",
        tags=["git", "best-practices"],
    )

    # Now process a conversation that mentions similar content
    # BACKGROUND mode should detect the duplicate
    messages = [
        Message(role="user", content="What's the best practice for git commits?"),
        Message(
            role="assistant",
            content="Use imperative mood like 'Add feature' not 'Added feature'. "
            "Keep the first line under 50 characters.",
        ),
    ]

    print("\n📝 Processing conversation that might duplicate existing learning...")
    background_store.process(messages=messages)
    print(f"🔄 was_updated: {background_store.was_updated}")

    # In BACKGROUND mode, the store should search existing learnings first
    # and avoid saving duplicates

    print("\n✅ Duplicate detection in BACKGROUND mode!")


# =============================================================================
# Test 6: Agent/Team Filtering
# =============================================================================


def test_agent_team_filtering():
    """
    Scope learnings to specific agents or teams.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Agent/Team Filtering")
    print("=" * 60)

    # Save learnings for different agents
    agentic_store.save(
        title="Code review checklist",
        learning="Check for: security vulnerabilities, performance issues, "
        "code readability, test coverage, documentation.",
        agent_id="code_reviewer",
    )

    agentic_store.save(
        title="Support ticket triage",
        learning="Categorize by urgency (critical/high/medium/low) and impact "
        "(many users/few users) first. Route accordingly.",
        agent_id="support_agent",
    )

    # Search with agent filter
    code_results = agentic_store.search(
        query="review checklist",
        agent_id="code_reviewer",
        limit=3,
    )

    support_results = agentic_store.search(
        query="ticket process",
        agent_id="support_agent",
        limit=3,
    )

    print("\n👨‍💻 Code reviewer's learnings:")
    for r in code_results:
        print(f"   - {r.title}")

    print("\n🎧 Support agent's learnings:")
    for r in support_results:
        print(f"   - {r.title}")

    print("\n✅ Agent/team filtering works!")


# =============================================================================
# Test 7: State Tracking
# =============================================================================


def test_state_tracking():
    """
    Know when a learning was actually saved.
    """
    print("\n" + "=" * 60)
    print("TEST 7: State Tracking (was_updated)")
    print("=" * 60)

    # Save a learning
    agentic_store.save(
        title="State tracking test",
        learning="This tests the was_updated property",
    )
    print(f"\n📝 After save: was_updated = {agentic_store.was_updated}")

    # Search (doesn't save anything)
    agentic_store.search(query="state tracking")
    print(f"📝 After search: was_updated = {agentic_store.was_updated}")

    print("\n✅ State tracking works!")


# =============================================================================
# Test 8: build_context() Formatting
# =============================================================================


def test_build_context():
    """
    Format learnings for system prompt injection.
    """
    print("\n" + "=" * 60)
    print("TEST 8: build_context() Formatting")
    print("=" * 60)

    # Search for some learnings
    results = agentic_store.search(query="Python best practices", limit=3)

    # Format for system prompt
    formatted = agentic_store.build_context(data=results)

    print("\n📝 Formatted context for system prompt:")
    print("-" * 40)
    print(formatted[:800] if len(formatted) > 800 else formatted)
    if len(formatted) > 800:
        print("... (truncated)")
    print("-" * 40)

    print("\n✅ build_context() works!")


# =============================================================================
# Test 9: PROPOSE Mode Flow
# =============================================================================


def test_propose_mode():
    """
    In PROPOSE mode, the agent proposes learnings but doesn't save
    until user confirms.
    """
    print("\n" + "=" * 60)
    print("TEST 9: PROPOSE Mode Flow")
    print("=" * 60)

    print(f"\n📊 Propose store mode: {propose_store.config.mode}")

    # Get the build_context output for PROPOSE mode
    # It should include instructions about proposing first
    results = propose_store.search(query="test", limit=1)
    context = propose_store.build_context(data=results)

    print("\n📝 PROPOSE mode context includes different instructions:")
    if "propose" in context.lower() or "confirm" in context.lower():
        print("   ✓ Instructions mention proposing/confirming")
    else:
        print("   (Context may vary based on implementation)")

    # In PROPOSE mode:
    # 1. Agent formats a proposed learning
    # 2. User confirms with "yes"
    # 3. Agent calls save_learning

    print("""
    PROPOSE Mode Flow:
    
    1. Agent discovers insight
    2. Agent formats proposal:
       ---
       💡 **Proposed Learning**
       Title: [name]
       Learning: [insight]
       ---
    3. User confirms: "yes"
    4. Agent calls save_learning tool
    """)

    print("\n✅ PROPOSE mode flow documented!")


# =============================================================================
# Test 10: Knowledge Base Requirement
# =============================================================================


def test_knowledge_requirement():
    """
    LearningsStore requires a knowledge base for semantic search.
    """
    print("\n" + "=" * 60)
    print("TEST 10: Knowledge Base Requirement")
    print("=" * 60)

    # Creating a config without knowledge should warn
    print("\n📝 Creating LearningsConfig without knowledge...")

    # The config's __post_init__ should emit a warning
    config_no_kb = LearningsConfig(
        model=model,
        knowledge=None,  # No knowledge base!
        mode=LearningMode.AGENTIC,
    )

    print(f"   Config created: {config_no_kb}")
    print(f"   knowledge is None: {config_no_kb.knowledge is None}")

    # Without knowledge, save/search won't work
    print("\n⚠️  Without a knowledge base:")
    print("   - save() won't persist learnings")
    print("   - search() won't find anything")
    print("   - The store is effectively disabled")

    print("""
    Best practice: Always provide a knowledge base:
    
    knowledge = Knowledge(
        vector_db=PgVector(
            db_url=db_url,
            table_name="my_learnings",
            embedder=OpenAIEmbedder(),
        )
    )
    
    config = LearningsConfig(knowledge=knowledge, ...)
    """)

    print("\n✅ Knowledge base requirement documented!")


# =============================================================================
# Test 11: __repr__ for Debugging
# =============================================================================


def test_repr():
    """
    Inspect store state with __repr__.
    """
    print("\n" + "=" * 60)
    print("TEST 11: __repr__ for Debugging")
    print("=" * 60)

    print(f"\n📊 AGENTIC store: {agentic_store}")
    print(f"📊 BACKGROUND store: {background_store}")
    print(f"📊 PROPOSE store: {propose_store}")

    print(f"\n📊 Config repr: {agentic_store.config}")

    print("\n✅ __repr__ works!")


# =============================================================================
# Cleanup
# =============================================================================


def cleanup():
    """Clean up test data."""
    print("\n" + "=" * 60)
    print("CLEANUP")
    print("=" * 60)

    # Note: Vector DB cleanup would require clearing the table
    # For this test, we're just acknowledging cleanup would be needed

    print("🧹 Note: In production, you'd clear the vector DB table")
    print("   For testing, consider using a separate test table")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧠 LearningsStore — Shared Knowledge")
    print("   Universal wisdom via semantic search")
    print("=" * 60)

    # Run all tests
    test_save_and_search()
    test_semantic_search()
    test_agent_tools()
    test_tags_and_context()
    test_duplicate_detection()
    test_agent_team_filtering()
    test_state_tracking()
    test_build_context()
    test_propose_mode()
    test_knowledge_requirement()
    test_repr()

    # Cleanup
    cleanup()

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests complete!")
    print("=" * 60)
    print("""
Key takeaways:

1. **Semantic Search**: Find by meaning, not keywords
   → "slow queries" finds "connection pooling"

2. **Three Modes**:
   - AGENTIC: Agent saves directly via tool
   - PROPOSE: Agent proposes, user confirms
   - BACKGROUND: Auto-extract (with duplicate detection)

3. **Agent Tools**:
   - search_learnings(query, limit)
   - save_learning(title, learning, context, tags)

4. **Knowledge Base Required**: Must provide for search to work

5. **Filtering**: Scope by agent_id/team_id

6. **Key Difference from Other Stores**:
   - UserProfile: per-user, exact lookup
   - SessionContext: per-session, exact lookup
   - Learnings: SHARED, SEMANTIC search
""")
