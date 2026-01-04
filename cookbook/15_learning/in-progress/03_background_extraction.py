"""
Learned Knowledge: Background Extraction
========================================
Automatic learning extraction from conversations.

In BACKGROUND mode, learnings are extracted automatically after
each conversation. The system identifies:
- Insights and patterns
- Rules of thumb
- Best practices
- Lessons learned

When to use BACKGROUND mode:
- Passive knowledge accumulation
- High-volume interactions
- When you don't want to burden the agent with save decisions

Trade-offs:
- May save more than needed (noise)
- Extra LLM call per conversation
- Less control over what's saved

For most use cases, AGENTIC or PROPOSE mode is recommended.

Run:
    python cookbook/15_learning/learned_knowledge/03_background_extraction.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
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
        table_name="background_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Background Learning Extraction
# ============================================================================
agent = Agent(
    name="Background Learning Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant. Have natural conversations.

Behind the scenes, valuable insights from our conversations are
automatically extracted and saved as learnings. You don't need to
explicitly save things - the system handles it.

You can still search prior learnings to help answer questions.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract
            enable_agent_tools=True,
            agent_can_search=True,  # Can still search
            # Custom instructions for extraction
            instructions="""\
Extract learnings that are:
- Generalizable rules or patterns
- Non-obvious insights
- Actionable best practices

Do NOT extract:
- User-specific information
- Trivial facts
- One-time solutions
""",
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Automatic Learning Extraction
# ============================================================================
def demo_auto_extraction():
    """Show automatic extraction from conversations."""
    print("=" * 60)
    print("Demo: Automatic Learning Extraction")
    print("=" * 60)

    user = "bg_learn_demo@example.com"

    # Conversation with embedded insights
    print("\n--- Conversation with insights ---\n")
    agent.print_response(
        "I spent a week debugging a production issue. Turns out the "
        "problem was that we were logging sensitive data in error messages. "
        "The fix was simple, but finding it was hard because the logs were "
        "so noisy. Lesson learned: always sanitize error messages in production.",
        user_id=user,
        session_id="auto_1",
        stream=True,
    )

    # Later, the learning should be searchable
    print("\n--- Search for related learnings ---\n")
    agent.print_response(
        "What have we learned about logging best practices?",
        user_id=user,
        session_id="auto_2",
        stream=True,
    )


# ============================================================================
# Demo: Multiple Insights
# ============================================================================
def demo_multiple_insights():
    """Show extracting multiple insights from one conversation."""
    print("\n" + "=" * 60)
    print("Demo: Multiple Insights from One Conversation")
    print("=" * 60)

    user = "multi_insight@example.com"

    print("\n--- Dense conversation ---\n")
    agent.print_response(
        """After years of building APIs, here's what I've learned:

        1. Always version your API from day one (/v1/...). Retrofitting is painful.

        2. Use consistent error formats. Clients shouldn't need special handling
           per endpoint.

        3. Rate limiting isn't optional - add it before you need it, not after
           you're being abused.

        4. Document everything, but especially breaking changes. A changelog
           is worth its weight in gold.

        What do you think about these patterns?""",
        user_id=user,
        session_id="multi_1",
        stream=True,
    )

    # Verify extraction
    print("\n--- Verify learnings were extracted ---\n")
    agent.print_response(
        "Search for API best practices we've discussed.",
        user_id=user,
        session_id="multi_2",
        stream=True,
    )


# ============================================================================
# Demo: Filtering Noise
# ============================================================================
def demo_filtering():
    """Show how the system filters out noise."""
    print("\n" + "=" * 60)
    print("Demo: Filtering Non-Learnings")
    print("=" * 60)

    user = "filter_demo@example.com"

    # Conversation without learnable content
    print("\n--- Small talk (should not extract) ---\n")
    agent.print_response(
        "Hey, how's it going? Nice weather today. What's 2 + 2?",
        user_id=user,
        session_id="filter_1",
        stream=True,
    )

    # User-specific info (should not extract as learning)
    print("\n--- User-specific (should not extract as learning) ---\n")
    agent.print_response(
        "My name is Bob and I work at Acme Corp. Remember that.",
        user_id=user,
        session_id="filter_2",
        stream=True,
    )

    # Actual insight (should extract)
    print("\n--- Actual insight (should extract) ---\n")
    agent.print_response(
        "I discovered that for Python web apps, using connection pooling "
        "can reduce database latency by 10x. PgBouncer or similar is essential "
        "for production workloads.",
        user_id=user,
        session_id="filter_3",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_auto_extraction()
    demo_multiple_insights()
    demo_filtering()

    print("\n" + "=" * 60)
    print("✅ Background mode: Automatic learning extraction")
    print("   Passive knowledge accumulation")
    print("   Custom instructions filter relevant content")
    print("=" * 60)
