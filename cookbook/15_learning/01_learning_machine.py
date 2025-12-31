"""
LearningMachine Cookbook
========================
Demonstrates the unified learning system for Agno agents.

LearningMachine ties together multiple learning types:
- User Profile: Long-term memory about users
- Session Context: State and summary for current session
- Learned Knowledge: Reusable insights with semantic search

Run this example:
    python cookbook/learning/01_learning_machine.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    BackgroundConfig,
    ExecutionTiming,
    KnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Database Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Knowledge base for learned insights (semantic search)
learnings_kb = Knowledge(
    name="Agent Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)

# =============================================================================
# Level 1: Dead Simple
# =============================================================================
# Just set learning=True and get sensible defaults


def create_simple_agent():
    """The simplest way to enable learning."""
    return Agent(
        name="Simple Learning Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        # This enables: user_profile, session_context, learned_knowledge
        # with default settings
        learning=True,
    )


# =============================================================================
# Level 2: Pick What You Want
# =============================================================================
# Choose which learning types to enable


def create_custom_agent():
    """Enable specific learning types with defaults."""
    return Agent(
        name="Custom Learning Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        learning=LearningMachine(
            db=db,
            knowledge=learnings_kb,
            # Enable user profile (remembers user info across sessions)
            user_profile=True,
            # Enable session context (tracks conversation state)
            session_context=True,
            # Enable learned knowledge (saves reusable insights)
            learned_knowledge=True,
        ),
    )


# =============================================================================
# Level 3: Full Control
# =============================================================================
# Configure each learning type in detail


def create_advanced_agent():
    """Full control over learning configuration."""
    return Agent(
        name="Advanced Learning Agent",
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        learning=LearningMachine(
            db=db,
            knowledge=learnings_kb,
            # User Profile: Background extraction with tool enabled
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
                background=BackgroundConfig(
                    timing=ExecutionTiming.PARALLEL,  # Extract while generating response
                    run_after_messages=2,  # Extract every 2 messages
                ),
                enable_tool=True,  # Agent can save memories via tool
            ),
            # Session Context: Enable planning mode
            session_context=SessionContextConfig(
                background=BackgroundConfig(
                    timing=ExecutionTiming.AFTER,  # Extract after response
                    run_after_messages=3,
                ),
                enable_planning=True,  # Track goal, plan, progress
            ),
            # Learned Knowledge: PROPOSE mode (ask user before saving)
            learned_knowledge=KnowledgeConfig(
                mode=LearningMode.PROPOSE,  # Agent proposes, user confirms
                enable_tool=True,
            ),
            # Custom instructions
            instructions="""\
When you discover a particularly valuable insight, propose saving it.
Focus on patterns that would help with similar future queries.
""",
        ),
    )


# =============================================================================
# Example Interactions
# =============================================================================


def demo_user_profile():
    """Demonstrate user profile learning."""
    print("=" * 60)
    print("Demo: User Profile Learning")
    print("=" * 60)

    agent = create_custom_agent()

    # First interaction - agent learns about user
    print("\n--- First Interaction ---")
    agent.print_response(
        "Hi! I'm Sarah, a senior engineer at Stripe working on payment infrastructure. "
        "I prefer concise responses with code examples.",
        user_id="sarah_123",
        stream=True,
    )

    # Second interaction - agent should remember Sarah
    print("\n--- Second Interaction (same user) ---")
    agent.print_response(
        "Can you help me design an API rate limiter?",
        user_id="sarah_123",
        stream=True,
    )


def demo_session_context():
    """Demonstrate session context learning."""
    print("=" * 60)
    print("Demo: Session Context Learning")
    print("=" * 60)

    agent = create_advanced_agent()  # Using planning mode
    session_id = "planning_session_001"

    # First message - establish goal
    print("\n--- Establishing Goal ---")
    agent.print_response(
        "I want to build a REST API for a todo app. Can you help me plan it out?",
        user_id="dev_user",
        session_id=session_id,
        stream=True,
    )

    # Continue the plan
    print("\n--- Continuing Plan ---")
    agent.print_response(
        "Great, let's start with the data models. What do you suggest?",
        user_id="dev_user",
        session_id=session_id,
        stream=True,
    )

    # Check progress
    print("\n--- Checking Progress ---")
    agent.print_response(
        "What have we covered so far?",
        user_id="dev_user",
        session_id=session_id,
        stream=True,
    )


def demo_learned_knowledge():
    """Demonstrate learned knowledge with PROPOSE mode."""
    print("=" * 60)
    print("Demo: Learned Knowledge (PROPOSE mode)")
    print("=" * 60)

    agent = create_custom_agent()

    # Ask a question that might produce a learning
    print("\n--- Query that might produce a learning ---")
    agent.print_response(
        "What are the key metrics to look at when evaluating ETFs? "
        "I'm comparing VTSAX and VTI.",
        user_id="investor_user",
        stream=True,
    )

    # The agent should propose a learning about ETF evaluation
    # User would then confirm with "yes" to save it

    # Simulate user confirming
    print("\n--- User confirms saving ---")
    agent.print_response(
        "yes",  # Confirm saving the proposed learning
        user_id="investor_user",
        stream=True,
    )


def demo_recall():
    """Demonstrate how learnings are recalled."""
    print("=" * 60)
    print("Demo: Recall Previous Learnings")
    print("=" * 60)

    agent = create_custom_agent()

    # Ask a related question - should recall the ETF learning
    print("\n--- Query that should recall previous learning ---")
    agent.print_response(
        "I'm looking at some bond ETFs. What should I focus on?",
        user_id="investor_user",
        stream=True,
    )


# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import sys

    demos = {
        "profile": demo_user_profile,
        "context": demo_session_context,
        "knowledge": demo_learned_knowledge,
        "recall": demo_recall,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        if demo_name in demos:
            demos[demo_name]()
        elif demo_name == "all":
            for name, demo_func in demos.items():
                print(f"\n{'#' * 60}")
                print(f"# Running: {name}")
                print(f"{'#' * 60}\n")
                demo_func()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("LearningMachine Cookbook")
        print("=" * 60)
        print("\nAvailable demos:")
        print("  profile   - User Profile learning")
        print("  context   - Session Context learning")
        print("  knowledge - Learned Knowledge with PROPOSE mode")
        print("  recall    - Recall previous learnings")
        print("  all       - Run all demos")
        print("\nUsage: python 01_learning_machine.py <demo>")
        print("\nRunning 'profile' demo by default...\n")
        demo_user_profile()
