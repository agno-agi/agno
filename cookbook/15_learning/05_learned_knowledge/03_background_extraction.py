"""
Learned Knowledge: Background Extraction
=========================================
Automatic extraction of insights from conversations.

In BACKGROUND mode:
- LLM analyzes each conversation for insights
- Automatically checks for duplicates
- Saves new learnings without user intervention

Trade-offs:
- Pro: Zero user friction
- Con: Extra LLM call per conversation
- Con: Less control over what gets saved

Run:
    python cookbook/15_learning/learned_knowledge/03_background_extraction.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Knowledge base for storing learnings
knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="background_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Background Extraction
# ============================================================================
agent = Agent(
    name="Background Learning Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant. Just focus on helping the user -
learning extraction happens automatically in the background.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.BACKGROUND,  # Automatic extraction
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper: Show stored learnings
# ============================================================================
def show_learnings(query: str = ""):
    """Display learnings matching query."""
    store = agent.learning.learned_knowledge_store
    if not store:
        print("No learned knowledge store configured")
        return

    results = store.search(query=query or "best practices", limit=10)
    if results:
        print("\n📚 Stored Learnings:")
        for i, learning in enumerate(results, 1):
            print(f"   {i}. {learning.title}")
            print(f"      {learning.learning[:80]}...")
    else:
        print("\n📚 No learnings found")


# ============================================================================
# Demo: Automatic Extraction
# ============================================================================
def demo_automatic_extraction():
    """Show insights extracted automatically from conversation."""
    print("=" * 60)
    print("Demo: Automatic Extraction")
    print("=" * 60)

    user = "auto_demo@example.com"

    # Conversation with implicit insights
    conversations = [
        (
            "session_1",
            "I discovered that adding index hints to our MySQL queries reduced "
            "execution time from 3 seconds to 50ms. The optimizer was choosing "
            "a suboptimal index because the statistics were stale.",
        ),
        (
            "session_2",
            "When deploying to Kubernetes, we found that setting resource limits "
            "too low caused random OOMKills. A good starting point is 2x the "
            "average memory usage observed during load testing.",
        ),
        (
            "session_3",
            "For Python type hints, using TypedDict instead of regular Dict "
            "gives you autocomplete in IDEs and catches key typos at lint time.",
        ),
    ]

    for session_id, message in conversations:
        print(f"\n--- {session_id} ---\n")
        agent.print_response(
            message,
            user_id=user,
            session_id=session_id,
            stream=True,
        )
        print("\n   ⟳ Background extraction runs after response...")

    # Show what was learned
    print("\n" + "-" * 40)
    show_learnings()


# ============================================================================
# Demo: Duplicate Detection
# ============================================================================
def demo_duplicate_detection():
    """Show how duplicates are handled."""
    print("\n" + "=" * 60)
    print("Demo: Duplicate Detection")
    print("=" * 60)

    user = "dup_demo@example.com"

    # First conversation - original insight
    print("\n--- First mention ---\n")
    agent.print_response(
        "Always validate user input on the server side, never trust "
        "client-side validation alone.",
        user_id=user,
        session_id="dup_1",
        stream=True,
    )

    # Second conversation - similar insight
    print("\n--- Similar insight (should detect duplicate) ---\n")
    agent.print_response(
        "Server-side input validation is essential. Don't rely on "
        "JavaScript validation.",
        user_id=user,
        session_id="dup_2",
        stream=True,
    )

    print("\n💡 Background extraction checks for duplicates before saving")
    print("   Similar insights should not create multiple entries")


# ============================================================================
# Demo: When Nothing is Learned
# ============================================================================
def demo_no_learning():
    """Show conversations that don't produce learnings."""
    print("\n" + "=" * 60)
    print("Demo: Conversations Without Learnings")
    print("=" * 60)

    user = "no_learn@example.com"

    conversations = [
        ("casual_1", "What's the weather like today?"),
        ("casual_2", "Tell me a joke"),
        ("casual_3", "Thanks for your help!"),
    ]

    for session_id, message in conversations:
        print(f"\n--- {session_id}: {message} ---")
        agent.print_response(
            message,
            user_id=user,
            session_id=session_id,
            stream=False,
        )

    print("\n💡 Simple conversations don't produce learnings")
    print("   The extraction LLM recognizes 'nothing worth saving here'")


# ============================================================================
# Performance Considerations
# ============================================================================
def performance_notes():
    """Print performance guidance."""
    print("\n" + "=" * 60)
    print("Performance Considerations")
    print("=" * 60)
    print("""
BACKGROUND MODE COSTS:

Each conversation triggers:
1. User response (normal LLM call)
2. Learning extraction (extra LLM call)
3. Duplicate search (embedding + vector search)
4. Optional: save to vector DB

OPTIMIZATION STRATEGIES:

1. Use a cheaper model for extraction
   ```python
   learning=LearningMachine(
       model=OpenAIChat(id="gpt-4o-mini"),  # Cheaper extractor
       learned_knowledge=LearnedKnowledgeConfig(
           mode=LearningMode.BACKGROUND,
       ),
   )
   ```

2. Only extract from meaningful conversations
   - Filter short conversations
   - Skip casual chit-chat

3. Batch extractions (future feature)
   - Extract from multiple conversations at once
   - Run during off-peak hours

4. Use AGENTIC mode instead
   - No extra LLM calls
   - Agent decides in-line

LATENCY IMPACT:

┌───────────────────┬─────────────────┬─────────────────┐
│ Mode              │ Response Time   │ Background Work │
├───────────────────┼─────────────────┼─────────────────┤
│ No learning       │ ~1s             │ None            │
│ AGENTIC           │ ~1s             │ None            │
│ BACKGROUND        │ ~1s + 1-2s*     │ Extraction      │
│ PROPOSE           │ ~1s             │ None            │
└───────────────────┴─────────────────┴─────────────────┘
* Background extraction runs async, may not block response
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_automatic_extraction()
    demo_duplicate_detection()
    demo_no_learning()
    performance_notes()

    print("\n" + "=" * 60)
    print("✅ BACKGROUND mode: Automatic learning extraction")
    print("   - Zero user friction")
    print("   - Extra LLM call per conversation")
    print("   - Built-in duplicate detection")
    print("=" * 60)
