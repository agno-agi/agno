"""
Learned Knowledge: Search and Apply
===================================
Using prior learnings to improve responses.

The real power of learned knowledge comes from applying it:
1. Agent receives a question
2. Agent searches for relevant learnings
3. Agent incorporates learnings into response
4. User gets a better answer

This creates a virtuous cycle:
- Save learnings → Better future answers → More valuable learnings

Run:
    python cookbook/15_learning/learned_knowledge/04_search_and_apply.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="search_apply_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Search and Apply
# ============================================================================
agent = Agent(
    name="Search Apply Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant with access to a knowledge base of learnings.

When answering questions:
1. FIRST search for relevant learnings
2. Incorporate applicable learnings into your response
3. Cite learnings when they influence your answer
4. Combine learnings with your general knowledge

When you find relevant learnings:
- Mention them explicitly: "Based on prior learnings..."
- Apply them to the specific situation
- Note if a learning is particularly relevant

When saving new learnings:
- Ensure they're generalizable
- Include context about when they apply
- Make them searchable with good keywords
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Setup: Seed Initial Learnings
# ============================================================================
def seed_learnings():
    """Seed the knowledge base with initial learnings."""
    print("=" * 60)
    print("Setup: Seeding Initial Learnings")
    print("=" * 60)

    user = "seed@example.com"

    learnings = [
        "Database: Always use connection pooling in production. Without it, "
        "creating new connections for each request adds ~50ms latency.",
        "Caching: Cache at multiple levels (CDN, application, database) but "
        "always plan for cache invalidation. Stale data is often worse than slow data.",
        "API Design: Use plural nouns for resources (/users not /user) and "
        "nest related resources logically (/users/{id}/posts).",
        "Error Handling: Never expose internal errors to users. Log the details, "
        "return a generic message with a correlation ID for support.",
        "Security: Store secrets in environment variables or a secrets manager, "
        "never in code or config files. Rotate credentials regularly.",
        "Testing: Write tests for the happy path first, then edge cases, then "
        "error conditions. Aim for 80% coverage on business logic.",
        "Deployment: Always use blue-green or canary deployments in production. "
        "The ability to instantly rollback is worth the complexity.",
        "Monitoring: Alert on symptoms (error rates, latency) not causes. "
        "High CPU doesn't always mean a problem; high error rate does.",
    ]

    for i, learning in enumerate(learnings, 1):
        print(f"\n--- Saving learning {i}/{len(learnings)} ---\n")
        agent.print_response(
            f"Please save this learning: {learning}",
            user_id=user,
            session_id=f"seed_{i}",
            stream=True,
        )

    print("\n✅ Initial learnings seeded\n")


# ============================================================================
# Demo: Search Before Answering
# ============================================================================
def demo_search_first():
    """Show agent searching for learnings before answering."""
    print("=" * 60)
    print("Demo: Search Before Answering")
    print("=" * 60)

    user = "search_demo@example.com"

    print("\n--- Question about databases ---\n")
    agent.print_response(
        "I'm setting up a new Python web app with PostgreSQL. "
        "What should I know about database connections?",
        user_id=user,
        session_id="search_1",
        stream=True,
    )

    print("\n--- Question about security ---\n")
    agent.print_response(
        "How should I handle API keys and passwords in my application?",
        user_id=user,
        session_id="search_2",
        stream=True,
    )


# ============================================================================
# Demo: Combining Multiple Learnings
# ============================================================================
def demo_combine_learnings():
    """Show combining multiple learnings for a comprehensive answer."""
    print("\n" + "=" * 60)
    print("Demo: Combining Multiple Learnings")
    print("=" * 60)

    user = "combine_demo@example.com"

    print("\n--- Broad question requiring multiple learnings ---\n")
    agent.print_response(
        "I'm building a production API for the first time. "
        "Give me a checklist of things I should consider.",
        user_id=user,
        session_id="combine_1",
        stream=True,
    )


# ============================================================================
# Demo: Learning + Current Context
# ============================================================================
def demo_context_plus_learning():
    """Show applying learnings to specific situations."""
    print("\n" + "=" * 60)
    print("Demo: Applying Learnings to Specific Context")
    print("=" * 60)

    user = "context_demo@example.com"

    print("\n--- Specific situation ---\n")
    agent.print_response(
        "My API is returning 500 errors intermittently. Users are complaining "
        "but I can't reproduce the issue. The error message just says "
        "'Internal Server Error'. How do I debug this?",
        user_id=user,
        session_id="context_1",
        stream=True,
    )


# ============================================================================
# Demo: No Relevant Learnings
# ============================================================================
def demo_no_learnings():
    """Show graceful handling when no learnings apply."""
    print("\n" + "=" * 60)
    print("Demo: Handling Missing Learnings")
    print("=" * 60)

    user = "miss_demo@example.com"

    print("\n--- Question without relevant learnings ---\n")
    agent.print_response(
        "What's the best way to make sourdough bread?",
        user_id=user,
        session_id="miss_1",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    seed_learnings()
    demo_search_first()
    demo_combine_learnings()
    demo_context_plus_learning()
    demo_no_learnings()

    print("\n" + "=" * 60)
    print("✅ Search and apply: Use learnings to improve answers")
    print("   Search first, then incorporate relevant learnings")
    print("   Cite learnings when they influence responses")
    print("=" * 60)
