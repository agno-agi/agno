"""
Learned Knowledge: Agentic Mode
===============================
Agent decides when to save learnings.

In AGENTIC mode (default for learnings), the agent has tools:
- `save_learning`: Save a reusable insight
- `search_learnings`: Find relevant prior learnings

The agent decides:
- What constitutes a valuable learning
- When to save vs when to just answer
- How to apply prior learnings to new situations

This mode is ideal because:
- Agent judgment filters out noise
- Users see when learnings are saved
- No hidden background LLM calls

Run:
    python cookbook/15_learning/learned_knowledge/01_agentic_mode.py
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
- Mention when a learning influenced your response

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
            mode=LearningMode.AGENTIC,  # Agent decides
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Discovering and Saving a Learning
# ============================================================================
def demo_discover_learning():
    """Show agent discovering and saving a learning."""
    print("=" * 60)
    print("Demo: Discovering and Saving a Learning")
    print("=" * 60)

    user = "learn_demo@example.com"

    # Conversation where agent discovers something worth saving
    print("\n--- Discovery conversation ---\n")
    agent.print_response(
        "I was comparing cloud providers and found that egress costs vary "
        "wildly - sometimes 10x difference for the same data transfer. "
        "This seems like an important pattern worth remembering.",
        user_id=user,
        session_id="discover_1",
        stream=True,
    )


# ============================================================================
# Demo: Applying Prior Learnings
# ============================================================================
def demo_apply_learning():
    """Show agent applying a prior learning."""
    print("\n" + "=" * 60)
    print("Demo: Applying Prior Learnings")
    print("=" * 60)

    user = "apply_demo@example.com"

    # First, establish a learning
    print("\n--- Establish a learning ---\n")
    agent.print_response(
        "Save this learning: When doing database migrations, always "
        "create a rollback plan before executing. Test the rollback "
        "in staging first.",
        user_id=user,
        session_id="establish_1",
        stream=True,
    )

    # Later, in a related conversation
    print("\n--- Related question (different session) ---\n")
    agent.print_response(
        "I need to migrate our production database from MySQL to PostgreSQL. "
        "What should I consider?",
        user_id=user,
        session_id="apply_1",
        stream=True,
    )


# ============================================================================
# Demo: Selective Saving
# ============================================================================
def demo_selective_saving():
    """Show agent being selective about what to save."""
    print("\n" + "=" * 60)
    print("Demo: Selective Saving")
    print("=" * 60)

    user = "selective_demo@example.com"

    # Worth saving (generalizable insight)
    print("\n--- Worth saving: Generalizable insight ---\n")
    agent.print_response(
        "I noticed that for Python projects, using `uv` instead of `pip` "
        "for dependency management is much faster - sometimes 10-100x faster. "
        "This is a game changer for CI/CD pipelines.",
        user_id=user,
        session_id="selective_1",
        stream=True,
    )

    # NOT worth saving (one-off fact)
    print("\n--- NOT worth saving: One-off fact ---\n")
    agent.print_response(
        "What time is it in Tokyo right now?",
        user_id=user,
        session_id="selective_2",
        stream=True,
    )

    # NOT worth saving (common knowledge)
    print("\n--- NOT worth saving: Common knowledge ---\n")
    agent.print_response(
        "How do I create a Python virtual environment?",
        user_id=user,
        session_id="selective_3",
        stream=True,
    )


# ============================================================================
# Demo: Building Knowledge Over Time
# ============================================================================
def demo_knowledge_building():
    """Show knowledge building over multiple sessions."""
    print("\n" + "=" * 60)
    print("Demo: Building Knowledge Over Time")
    print("=" * 60)

    user = "builder_demo@example.com"

    # Learning 1
    print("\n--- Learning 1: API Design ---\n")
    agent.print_response(
        "Save this: For REST APIs, using plural nouns for resources "
        "(e.g., /users not /user) is more consistent and intuitive.",
        user_id=user,
        session_id="build_1",
        stream=True,
    )

    # Learning 2
    print("\n--- Learning 2: Error Handling ---\n")
    agent.print_response(
        "Save this: Always return structured error responses with "
        "error codes, not just messages. This helps clients handle "
        "errors programmatically.",
        user_id=user,
        session_id="build_2",
        stream=True,
    )

    # Learning 3
    print("\n--- Learning 3: Pagination ---\n")
    agent.print_response(
        "Save this: For list endpoints, always support cursor-based "
        "pagination over offset pagination. It's more efficient for "
        "large datasets and doesn't have page drift issues.",
        user_id=user,
        session_id="build_3",
        stream=True,
    )

    # Apply all learnings
    print("\n--- Apply learnings to new task ---\n")
    agent.print_response(
        "I'm designing a new API for a todo list application. "
        "What best practices should I follow?",
        user_id=user,
        session_id="build_4",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_discover_learning()
    demo_apply_learning()
    demo_selective_saving()
    demo_knowledge_building()

    print("\n" + "=" * 60)
    print("✅ Agentic mode: Agent decides what's worth saving")
    print("   save_learning = store insights")
    print("   search_learnings = find and apply")
    print("=" * 60)
