"""
Continuous Learning Agent
===========================================
An agent that improves with EVERY interaction.

The key patterns:
1. ALWAYS search learnings before responding
2. ALWAYS extract from every conversation (BACKGROUND mode)
3. Track what worked (implicit feedback via follow-up questions)

Over time, this agent accumulates knowledge and gets measurably better.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="continuous_learnings"),
)

# =============================================================================
# Continuous Learning Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Continuous Learning Agent that improves with every interaction.

## Your Learning Loop

### Before Every Response:
1. Call `search_learnings` with key concepts from the query
2. Apply any relevant insights naturally
3. Note patterns from similar past interactions

### During Response:
4. Provide the best answer using all available knowledge
5. Be specific and actionable

### After Responding (Reflect):
6. Did this interaction reveal something new?
7. If yes, save it via `save_learning`

## What to Learn

SAVE when you discover:
- Patterns that apply across similar questions
- Best practices that weren't obvious
- Common mistakes and how to avoid them
- Effective explanations that worked

DON'T SAVE:
- One-off facts
- User-specific info (that goes in their profile)
- Obvious/common knowledge

## Learning Quality

Good learnings are:
- **Specific**: Not vague generalizations
- **Actionable**: Can be directly applied
- **Validated**: Based on what actually worked

## Examples of Good Learnings

✅ "When explaining async/await, start with the restaurant analogy - 
   waiter takes orders (async calls) while kitchen cooks (background work)"

✅ "For PostgreSQL index issues, always check: 1) index exists, 
   2) query uses it (EXPLAIN), 3) statistics are current (ANALYZE)"

❌ "Databases are important" (too vague)
❌ "User prefers Python" (goes in user profile, not learnings)
"""

# =============================================================================
# Create Continuous Learning Agent
# =============================================================================
agent = Agent(
    name="Continuous Learner",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o-mini"),  # Cheap model for extraction
        knowledge=knowledge,
        # ALL learning types enabled, ALL in BACKGROUND mode
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
        session_context=SessionContextConfig(),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,  # Agent decides what's worth saving
            enable_search=True,
            enable_save=True,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Metrics Tracking
# =============================================================================
class LearningMetrics:
    """Track learning metrics over time."""

    def __init__(self, agent):
        self.agent = agent

    def count_learnings(self) -> int:
        """Count total learnings."""
        store = self.agent.learning.stores.get("learned_knowledge")
        if not store:
            return 0
        # Search with broad query to get count
        results = store.search("software development best practices patterns", limit=100)
        return len(results)

    def count_user_profiles(self) -> int:
        """Count users with profiles (rough estimate)."""
        return 0  # Would need DB query

    def report(self):
        """Print metrics report."""
        print(f"\n📊 Learning Metrics")
        print(f"   Learnings stored: {self.count_learnings()}")


metrics = LearningMetrics(agent)


# =============================================================================
# Demo: Watch the agent learn
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Continuous Learning Agent")
    print("=" * 60)
    print("Watch the agent accumulate knowledge over interactions.\n")

    # Simulate multiple interactions
    interactions = [
        {
            "user": "alice@example.com",
            "query": "How do I handle errors in async Python code?",
        },
        {
            "user": "bob@example.com",
            "query": "What's the best way to structure error handling in async functions?",
        },
        {
            "user": "carol@example.com",
            "query": "My async code silently fails. How do I debug it?",
        },
        {
            "user": "dave@example.com",
            "query": "How should I test async Python code?",
        },
        {
            "user": "eve@example.com",
            "query": "Any tips for async error handling?",
        },
    ]

    for i, interaction in enumerate(interactions, 1):
        print(f"\n{'=' * 60}")
        print(f"Interaction {i}/{len(interactions)}: {interaction['user']}")
        print("=" * 60)

        agent.print_response(
            interaction["query"],
            user_id=interaction["user"],
            session_id=f"session_{i}",
            stream=True,
        )

        # Show learning progress
        metrics.report()

    # Final summary
    print("\n" + "=" * 60)
    print("Final Learning State")
    print("=" * 60)

    # Show what was learned
    results = agent.learning.stores["learned_knowledge"].search(
        query="async error handling Python",
        limit=10,
    )

    if results:
        print("\n📚 Learned Patterns:")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            learning = getattr(r, 'learning', str(r))[:100]
            print(f"\n   {title}")
            print(f"   {learning}...")
    else:
        print("\n📚 No patterns learned yet (may need more interactions)")

    print("\n" + "=" * 60)
    print("Key Insight")
    print("=" * 60)
    print("""
    The agent improves because:
    
    1. It SEARCHES before responding
       - Later questions benefit from earlier answers
    
    2. It EXTRACTS from every conversation
       - Patterns accumulate over time
    
    3. It ADAPTS to each user
       - Personalization via user profiles
    
    Run this cookbook multiple times to see knowledge compound!
    """)
