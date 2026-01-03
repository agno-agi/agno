"""
PROPOSE Mode: Human-in-the-Loop Learning
===========================================
In PROPOSE mode, the agent proposes learnings but waits for user
confirmation before saving them.

This creates a quality control loop:
1. Agent discovers a potential insight
2. Agent formats and proposes it to the user
3. User reviews and says "yes" or "no"
4. Only confirmed learnings are saved

Perfect for:
- High-value knowledge bases
- Teams that want human validation
- Building curated insight collections
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import LearningMachine, LearningMode, LearnedKnowledgeConfig
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="propose_mode_learnings"),
)

# =============================================================================
# Instructions for PROPOSE mode
# =============================================================================
INSTRUCTIONS = """\
You are a helpful assistant that learns from conversations.

When you discover a valuable, reusable insight, propose saving it using this format:

---
**💡 Proposed Learning**

**Title:** [Short, descriptive title]
**Learning:** [The specific insight - actionable and concrete]
**Context:** [When this applies]

Save this learning? (yes/no)
---

Only propose learnings that are:
- Specific and actionable (not vague)
- Reusable across different situations
- Not obvious or common knowledge

Wait for user confirmation before calling save_learning.
If user says "no", acknowledge and move on.
"""

# =============================================================================
# Create PROPOSE Mode Agent
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        user_profile=True,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,
            enable_save=True,
            enable_search=True,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Search learnings
# =============================================================================
def show_learnings():
    """Show all saved learnings."""
    results = agent.learning.stores["learned_knowledge"].search(
        query="software development best practices",
        limit=10,
    )
    if results:
        print("\n📚 Saved Learnings:")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            learning = getattr(r, 'learning', str(r))[:60]
            print(f"   > {title}: {learning}...")
    else:
        print("\n📚 No learnings saved yet.")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "henry@example.com"
    session_id = "propose_demo"

    # --- Conversation that generates an insight ---
    print("=" * 60)
    print("Conversation: Agent discovers an insight")
    print("=" * 60)
    agent.print_response(
        "I've been debugging a race condition for 3 days. Finally found it - "
        "we were reading from a shared map without a mutex. The bug only "
        "appeared under high load because that's when the timing was right "
        "for concurrent access. What's the lesson here?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_learnings()

    # --- User confirms ---
    print("=" * 60)
    print("User confirms the learning")
    print("=" * 60)
    agent.print_response(
        "yes",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_learnings()

    # --- Another conversation, agent proposes ---
    print("=" * 60)
    print("Another conversation with potential insight")
    print("=" * 60)
    agent.print_response(
        "We had an outage because our retry logic didn't have exponential backoff. "
        "When the downstream service recovered, we hammered it with all the "
        "queued retries at once and brought it down again.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # --- User declines ---
    print("=" * 60)
    print("User declines this learning")
    print("=" * 60)
    agent.print_response(
        "no, that's too specific to our situation",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_learnings()

    # --- Later: learnings help new questions ---
    print("=" * 60)
    print("Later: Learnings help with new questions")
    print("=" * 60)
    agent.print_response(
        "I'm writing concurrent Go code. What should I watch out for?",
        user_id="isaac@example.com",  # Different user
        session_id="new_session",
        stream=True,
    )
