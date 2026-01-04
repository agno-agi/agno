"""
Combined: Full Learning Machine
===============================
All four learning stores working together.

This example enables:
- **User Profile**: Personal memory (BACKGROUND)
- **Session Context**: Task tracking (with planning)
- **Entity Memory**: External knowledge (AGENTIC)
- **Learned Knowledge**: Reusable insights (AGENTIC)

Use case: A comprehensive AI assistant that:
- Remembers who you are
- Tracks what you're working on
- Knows about your projects/accounts
- Learns from every interaction

Run:
    python cookbook/15_learning/combined/03_full_learning_machine.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearningMachine,
    UserProfileConfig,
    SessionContextConfig,
    LearnedKnowledgeConfig,
    EntityMemoryConfig,
    LearningMode,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# Knowledge base for learnings
knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="full_agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Full Learning Machine
# ============================================================================
agent = Agent(
    name="Full Learning Agent",
    model=model,
    db=db,
    instructions="""\
You are a comprehensive AI assistant with four types of memory:

1. **User Profile** (automatic): I remember who you are across sessions
2. **Session Context** (automatic): I track our current task and progress
3. **Entity Memory** (tools): I can track companies, people, projects
4. **Learned Knowledge** (tools): I can save and retrieve reusable insights

For entities: Use create_entity, add_fact, add_event, add_relationship
For learnings: Use save_learning, search_learnings

Be proactive about:
- Tracking entities mentioned in conversation
- Saving valuable insights as learnings
- Applying prior learnings when relevant
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Complete Interaction
# ============================================================================
def demo_complete_interaction():
    """Show all four stores in action."""
    print("=" * 60)
    print("Demo: Full Learning Machine in Action")
    print("=" * 60)

    user = "full_demo@example.com"
    session = "full_demo_session"

    # ========================================
    # Part 1: Establish User Context
    # ========================================
    print("\n" + "-" * 40)
    print("Part 1: User Profile (BACKGROUND)")
    print("-" * 40)

    print("\n--- User introduces themselves ---\n")
    agent.print_response(
        "Hi! I'm Chris, a product manager at a SaaS startup. "
        "I'm technical but prefer high-level explanations. "
        "I'm currently focused on our enterprise launch.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # ========================================
    # Part 2: Start a Task (Session Context)
    # ========================================
    print("\n" + "-" * 40)
    print("Part 2: Session Context (Planning)")
    print("-" * 40)

    print("\n--- Start a complex task ---\n")
    agent.print_response(
        "Help me prepare for my meeting with EnterpriseClient tomorrow. "
        "I need to: "
        "1. Understand their requirements "
        "2. Prepare a demo "
        "3. Have answers for security questions",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # ========================================
    # Part 3: Track Entity (Entity Memory)
    # ========================================
    print("\n" + "-" * 40)
    print("Part 3: Entity Memory (AGENTIC)")
    print("-" * 40)

    print("\n--- Track the client as an entity ---\n")
    agent.print_response(
        "About EnterpriseClient: They're a Fortune 100 company in healthcare. "
        "Their IT director is Sarah Johnson. "
        "They need SOC2 compliance and HIPAA support. "
        "Budget is $200K-500K annually. "
        "Please track all of this.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # ========================================
    # Part 4: Save a Learning (Learned Knowledge)
    # ========================================
    print("\n" + "-" * 40)
    print("Part 4: Learned Knowledge (AGENTIC)")
    print("-" * 40)

    print("\n--- Discover and save an insight ---\n")
    agent.print_response(
        "I just realized something from my last 10 enterprise deals: "
        "The security questionnaire is always the bottleneck. "
        "Starting it early, even before the demo, saves 2-3 weeks. "
        "This seems like a valuable pattern - please save it.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # ========================================
    # Part 5: Apply Everything
    # ========================================
    print("\n" + "-" * 40)
    print("Part 5: Combined Context")
    print("-" * 40)

    print("\n--- Query using all context ---\n")
    agent.print_response(
        "Given everything we've discussed, what should my priorities be "
        "for the EnterpriseClient meeting preparation?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Context Persistence
# ============================================================================
def demo_persistence():
    """Show how context persists across sessions."""
    print("\n" + "=" * 60)
    print("Demo: Context Persists Across Sessions")
    print("=" * 60)

    user = "full_demo@example.com"  # Same user
    session = "new_session"         # New session

    print("\n--- New session, same user ---\n")
    agent.print_response(
        "Hey, I'm preparing for another enterprise meeting. "
        "What should I remember based on our previous discussions?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n💡 Agent should remember:")
    print("   - User: Chris, PM at SaaS startup (User Profile)")
    print("   - EnterpriseClient info (Entity Memory)")
    print("   - Security questionnaire pattern (Learned Knowledge)")
    print("   - Note: Session context is new (different session)")


# ============================================================================
# Demo: Cross-Store Queries
# ============================================================================
def demo_cross_store():
    """Show queries that span multiple stores."""
    print("\n" + "=" * 60)
    print("Demo: Cross-Store Queries")
    print("=" * 60)

    user = "cross_demo@example.com"
    session = "cross_session"

    # Set up context
    print("\n--- Set up context ---\n")
    agent.print_response(
        "I'm Dana, a solutions architect. "
        "Track these prospects: TechCorp (uses AWS, needs migration help) "
        "and DataInc (uses Azure, needs security review).",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Save a learning
    print("\n--- Save a learning ---\n")
    agent.print_response(
        "Save this: For cloud migrations, always start with a dependency map. "
        "Missing dependencies are the #1 cause of failed migrations.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Cross-store query
    print("\n--- Cross-store query ---\n")
    agent.print_response(
        "Looking at my prospects, which one should I prioritize "
        "and what approach should I take based on our learnings?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_complete_interaction()
    demo_persistence()
    demo_cross_store()

    print("\n" + "=" * 60)
    print("✅ Full Learning Machine combines all four stores:")
    print("   User Profile → who you are")
    print("   Session Context → what we're doing")
    print("   Entity Memory → external knowledge")
    print("   Learned Knowledge → reusable insights")
    print("=" * 60)
