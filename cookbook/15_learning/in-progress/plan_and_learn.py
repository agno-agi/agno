"""
Production: Plan and Learn Agent
================================
Combining session planning with knowledge capture.

This pattern is ideal for complex, multi-step tasks where:
1. Planning improves task execution
2. Learnings from one task improve future tasks
3. Users have ongoing, evolving needs

The "Plan and Learn" pattern:
- Session Context with planning tracks current task
- Learned Knowledge captures reusable insights
- User Profile remembers preferences across tasks

Run:
    python cookbook/15_learning/production/plan_and_learn.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserProfileConfig,
    SessionContextConfig,
    LearnedKnowledgeConfig,
)
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
        table_name="plan_and_learn_kb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Plan and Learn Agent
# ============================================================================
plan_and_learn_agent = Agent(
    name="Plan and Learn Assistant",
    agent_id="plan-and-learn",
    model=model,
    db=db,
    instructions="""\
You are a strategic assistant that plans tasks and learns from experience.

Your approach:
1. PLAN: Break down complex tasks into clear steps
2. EXECUTE: Work through steps methodically
3. LEARN: Capture insights for future similar tasks

When starting a task:
- Understand the goal clearly
- Search for relevant learnings from past tasks
- Create a plan with concrete steps
- Update progress as you work

When completing a task:
- Summarize what was accomplished
- Identify learnings worth saving
- Note what worked well and what didn't

Learnings to capture:
- Effective approaches to common problems
- User-specific preferences for certain tasks
- Gotchas and edge cases discovered
- Efficient shortcuts or patterns

Be proactive about:
- Applying past learnings to new situations
- Suggesting plan improvements based on experience
- Remembering user preferences for task execution
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_update_profile=True,
            enable_add_memory=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Track goal, plan, progress
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="plan_and_learn",
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: First Task (Learning)
# ============================================================================
def demo_first_task():
    """First task - establish learnings."""
    print("=" * 60)
    print("Demo: First Task (Establishing Learnings)")
    print("=" * 60)

    user = "pal_demo@example.com"
    session = "task_1_api_design"

    # Start task
    print("\n--- Start: API Design Task ---\n")
    plan_and_learn_agent.print_response(
        "Help me design a REST API for a task management app. "
        "I need endpoints for users, projects, and tasks.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Work through plan
    print("\n--- Progress: User endpoints ---\n")
    plan_and_learn_agent.print_response(
        "I've designed the user endpoints following your suggestions. "
        "The /users resource handles CRUD operations with proper validation. "
        "What's next?",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Complete with learning
    print("\n--- Complete: Capture learning ---\n")
    plan_and_learn_agent.print_response(
        "Done! I learned that using plural nouns and consistent error formats "
        "made the API much cleaner. Save this as a learning for future API work.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Second Task (Applying Learnings)
# ============================================================================
def demo_second_task():
    """Second task - apply learnings from first."""
    print("\n" + "=" * 60)
    print("Demo: Second Task (Applying Learnings)")
    print("=" * 60)

    user = "pal_demo@example.com"
    session = "task_2_new_api"

    # New similar task
    print("\n--- Start: New API Task ---\n")
    plan_and_learn_agent.print_response(
        "I need to design another API, this time for an e-commerce app. "
        "Products, orders, and customers.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Long-Running Task
# ============================================================================
def demo_long_task():
    """Multi-session task with plan persistence."""
    print("\n" + "=" * 60)
    print("Demo: Long-Running Task (Plan Persistence)")
    print("=" * 60)

    user = "long_task_demo@example.com"
    session = "migration_project"

    # Day 1: Start
    print("\n--- Day 1: Start migration project ---\n")
    plan_and_learn_agent.print_response(
        "Help me plan a database migration from MySQL to PostgreSQL. "
        "This is a big project - production database with 50 tables.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Day 1: Progress
    print("\n--- Day 1: Complete schema analysis ---\n")
    plan_and_learn_agent.print_response(
        "I've analyzed all 50 tables. Found 10 that use MySQL-specific features. "
        "Mark this step as complete.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Day 2: Resume
    print("\n--- Day 2: Resume ---\n")
    plan_and_learn_agent.print_response(
        "Back to work on the migration. Where were we?",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Pattern Summary
# ============================================================================
def pattern_summary():
    """Print the Plan and Learn pattern summary."""
    print("\n" + "=" * 60)
    print("Plan and Learn Pattern")
    print("=" * 60)
    print("""
┌─────────────────────────────────────────────────────────────┐
│                    PLAN AND LEARN PATTERN                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   SESSION   │    │   LEARNED   │    │    USER     │     │
│  │   CONTEXT   │    │  KNOWLEDGE  │    │   PROFILE   │     │
│  │             │    │             │    │             │     │
│  │ • Goal      │    │ • Patterns  │    │ • Prefs     │     │
│  │ • Plan      │    │ • Best      │    │ • Style     │     │
│  │ • Progress  │    │   practices │    │ • Context   │     │
│  │ • Summary   │    │ • Gotchas   │    │ • History   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│        │                  │                  │              │
│        └──────────────────┼──────────────────┘              │
│                           │                                 │
│                    ┌──────▼──────┐                          │
│                    │   AGENT     │                          │
│                    │  RESPONSE   │                          │
│                    └─────────────┘                          │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ FLOW:                                                       │
│ 1. Recall user profile and search relevant learnings        │
│ 2. Create/update plan for current session                   │
│ 3. Execute with awareness of past insights                  │
│ 4. Capture new learnings for future use                     │
│ 5. Update user profile with new preferences                 │
└─────────────────────────────────────────────────────────────┘

IDEAL FOR:
- Complex, multi-step tasks
- Recurring task types
- Users with evolving needs
- Knowledge-intensive work
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_first_task()
    demo_second_task()
    demo_long_task()
    pattern_summary()

    print("\n" + "=" * 60)
    print("✅ Plan and Learn: Strategic task execution")
    print("   Session Context tracks current task progress")
    print("   Learned Knowledge captures reusable insights")
    print("   User Profile remembers preferences")
    print("=" * 60)
