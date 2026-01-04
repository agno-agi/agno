"""
Learned Knowledge: Propose Mode
===============================
Human approval before saving.

PROPOSE mode adds a human-in-the-loop step:
1. Agent proposes a learning
2. User reviews the proposal
3. User confirms or rejects
4. Only confirmed learnings are saved

This is ideal for:
- High-stakes knowledge bases
- Quality control
- Compliance requirements
- Learning from user feedback

The agent uses `propose_learning` instead of `save_learning`.

Run:
    python cookbook/15_learning/learned_knowledge/02_propose_mode.py
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
        table_name="propose_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Propose Mode
# ============================================================================
agent = Agent(
    name="Propose Learning Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant that learns with human oversight.

When you identify a potential learning:
- Use `propose_learning` to suggest it
- The user will review and decide whether to save
- Wait for confirmation before considering it saved

Propose learnings that are:
- Generalizable across situations
- Valuable for future reference
- Not user-specific (use memory for personal info)

When proposing, include:
- The learning itself
- Context about when it applies
- Why it's valuable
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,  # Human approval required
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Propose → Approve Flow
# ============================================================================
def demo_propose_approve():
    """Show the propose → approve workflow."""
    print("=" * 60)
    print("Demo: Propose → Approve Flow")
    print("=" * 60)

    user = "propose_demo@example.com"

    # Agent proposes a learning
    print("\n--- Agent proposes a learning ---\n")
    agent.print_response(
        "I discovered something important: When building microservices, "
        "always implement circuit breakers for external calls. Without them, "
        "one failing service can cascade and take down everything.",
        user_id=user,
        session_id="propose_1",
        stream=True,
    )

    # User approves (in production, this would be a UI action)
    print("\n--- User approves ---\n")
    agent.print_response(
        "Yes, please save that learning about circuit breakers.",
        user_id=user,
        session_id="propose_1",
        stream=True,
    )


# ============================================================================
# Demo: Propose → Reject Flow
# ============================================================================
def demo_propose_reject():
    """Show what happens when user rejects a proposal."""
    print("\n" + "=" * 60)
    print("Demo: Propose → Reject Flow")
    print("=" * 60)

    user = "reject_demo@example.com"

    # Agent proposes
    print("\n--- Agent proposes ---\n")
    agent.print_response(
        "I think this is worth saving: Always use MongoDB for web applications.",
        user_id=user,
        session_id="reject_1",
        stream=True,
    )

    # User rejects
    print("\n--- User rejects ---\n")
    agent.print_response(
        "No, don't save that. It's too broad and not always true. "
        "The database choice depends on the use case.",
        user_id=user,
        session_id="reject_1",
        stream=True,
    )


# ============================================================================
# Demo: Propose with Refinement
# ============================================================================
def demo_propose_refine():
    """Show refining a proposal before saving."""
    print("\n" + "=" * 60)
    print("Demo: Propose → Refine → Approve")
    print("=" * 60)

    user = "refine_demo@example.com"

    # Initial proposal
    print("\n--- Initial proposal ---\n")
    agent.print_response(
        "I'd like to save: Python is the best language for data science.",
        user_id=user,
        session_id="refine_1",
        stream=True,
    )

    # User requests refinement
    print("\n--- User requests refinement ---\n")
    agent.print_response(
        "That's too absolute. Can you refine it to be more nuanced? "
        "Include when other languages might be better.",
        user_id=user,
        session_id="refine_1",
        stream=True,
    )

    # Refined proposal
    print("\n--- User approves refined version ---\n")
    agent.print_response(
        "Yes, save that refined version.",
        user_id=user,
        session_id="refine_1",
        stream=True,
    )


# ============================================================================
# Demo: Quality Control
# ============================================================================
def demo_quality_control():
    """Show how propose mode enables quality control."""
    print("\n" + "=" * 60)
    print("Demo: Quality Control via Propose Mode")
    print("=" * 60)

    user = "quality_demo@example.com"

    print("""
    In production, PROPOSE mode enables:

    1. Human Review Interface
       - Queue of proposed learnings
       - Accept/Reject/Edit buttons
       - Categorization and tagging

    2. Quality Metrics
       - Acceptance rate per topic
       - Most valuable learnings
       - Agent learning patterns

    3. Compliance
       - Audit trail of approvals
       - Who approved what, when
       - Rejection reasons logged

    4. Continuous Improvement
       - Feedback to agent on rejections
       - Pattern learning from acceptances
       - Evolving quality criteria
    """)

    # Example interaction
    print("\n--- High-quality proposal ---\n")
    agent.print_response(
        "Based on our troubleshooting today, I'd propose saving: "
        "When debugging memory leaks in Python, always check for "
        "circular references in data structures with __del__ methods. "
        "The garbage collector can't collect cycles with custom finalizers.",
        user_id=user,
        session_id="quality_1",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_propose_approve()
    demo_propose_reject()
    demo_propose_refine()
    demo_quality_control()

    print("\n" + "=" * 60)
    print("✅ Propose mode: Human approval before saving")
    print("   Ideal for quality control and compliance")
    print("   Enables refinement before committing")
    print("=" * 60)
