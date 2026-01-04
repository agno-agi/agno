"""
Learned Knowledge: Agentic Mode
===============================
Agent decides when to save learnings.

In AGENTIC mode (default for learnings), the agent has tools:
- `save_learning`: Save a reusable insight
- `search_learnings`: Find relevant prior learnings

The agent decides what constitutes a valuable learning
and when to apply prior learnings.

Run:
    python cookbook/15_learning/learned_knowledge/01_agentic_mode.py
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
        table_name="agentic_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Agentic Learnings
# ============================================================================
agent = Agent(
    name="Agentic Learning Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant that learns from interactions.

When you discover a valuable, reusable insight:
- Use `save_learning` to store it
- Be selective - only save things worth remembering
- Include context about when this learning applies

When answering questions:
- Use `search_learnings` to find relevant prior knowledge
- Apply learnings when relevant

Good learnings are:
- Generalizable (apply to multiple situations)
- Non-obvious (not common knowledge)
- Actionable (help make better decisions)

Don't save:
- Basic facts easily looked up
- One-off solutions
- User-specific information (use memory for that)
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
# Demo: Save and Apply Learning
# ============================================================================
def demo_save_and_apply():
    """Show saving a learning and applying it later."""
    print("=" * 60)
    print("Demo: Save and Apply Learning")
    print("=" * 60)

    user = "learn_demo@example.com"

    # Save a learning
    print("\n--- Save a learning ---\n")
    agent.print_response(
        "Save this insight: When comparing cloud providers, always "
        "check egress costs first - they can vary by 10x between providers "
        "and often get overlooked in initial estimates.",
        user_id=user,
        session_id="save_1",
        stream=True,
    )

    # Apply the learning
    print("\n--- Apply the learning ---\n")
    agent.print_response(
        "I need to choose between AWS and GCP for a new project. "
        "What should I consider?",
        user_id=user,
        session_id="apply_1",
        stream=True,
    )


# ============================================================================
# Demo: Building Knowledge Over Time
# ============================================================================
def demo_knowledge_building():
    """Show knowledge accumulating over time."""
    print("\n" + "=" * 60)
    print("Demo: Building Knowledge Over Time")
    print("=" * 60)

    user = "builder@example.com"

    learnings = [
        "Save this: For database migrations, always test rollback "
        "procedures in staging before running in production.",
        "Save this: When doing API versioning, prefer URL path versioning "
        "(like /v1/) over header versioning for better debuggability.",
        "Save this: For Python projects, using 'uv' instead of 'pip' "
        "is 10-100x faster and significantly improves CI/CD times.",
    ]

    for i, learning in enumerate(learnings, 1):
        print(f"\n--- Learning {i} ---\n")
        agent.print_response(
            learning,
            user_id=user,
            session_id=f"build_{i}",
            stream=True,
        )

    # Apply multiple learnings
    print("\n--- Apply learnings to task ---\n")
    agent.print_response(
        "I'm setting up a new Python API project with a PostgreSQL database. "
        "What best practices should I follow?",
        user_id=user,
        session_id="apply_all",
        stream=True,
    )


# ============================================================================
# Demo: Selective Saving
# ============================================================================
def demo_selective():
    """Show agent being selective about what to save."""
    print("\n" + "=" * 60)
    print("Demo: Selective Saving")
    print("=" * 60)

    user = "selective@example.com"

    print("\n--- Worth saving (generalizable) ---\n")
    agent.print_response(
        "I noticed that adding request IDs to all API calls makes "
        "debugging distributed systems way easier. Should we save this?",
        user_id=user,
        session_id="selective_1",
        stream=True,
    )

    print("\n--- NOT worth saving (one-off) ---\n")
    agent.print_response(
        "What's the capital of France?",
        user_id=user,
        session_id="selective_2",
        stream=True,
    )

    print("\n--- NOT worth saving (user-specific) ---\n")
    agent.print_response(
        "My name is Bob and I work at Acme Corp.",
        user_id=user,
        session_id="selective_3",
        stream=True,
    )

    print("\n💡 Agent should save the API pattern but not the trivia or personal info")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_save_and_apply()
    demo_knowledge_building()
    demo_selective()

    print("\n" + "=" * 60)
    print("✅ AGENTIC mode: Agent controls learnings")
    print("   - save_learning: Store insights")
    print("   - search_learnings: Find and apply")
    print("   - Be selective about what to save")
    print("=" * 60)
